"""Demonstrate combustive mixture with Pyrometheus."""

__copyright__ = """
Copyright (C) 2020 University of Illinois Board of Trustees
"""

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
import logging
import numpy as np
import pyopencl as cl
import pyopencl.tools as cl_tools
from functools import partial

from meshmode.array_context import PyOpenCLArrayContext

from meshmode.mesh import BTAG_ALL, BTAG_NONE  # noqa
from grudge.eager import EagerDGDiscretization
from grudge.shortcuts import make_visualizer

from logpyle import IntervalTimer, set_dt
from mirgecom.euler import extract_vars_for_logging, units_for_logging
from mirgecom.euler import euler_operator
from mirgecom.navierstokes import ns_operator
from mirgecom.simutil import (
    get_sim_timestep,
    generate_and_distribute_mesh,
    write_visfile,
)
from mirgecom.io import make_init_message
from mirgecom.mpi import mpi_entry_point
from mirgecom.integrators import rk4_step, euler_step
from mirgecom.steppers import advance_state
from mirgecom.initializers import (
    MixtureInitializer,
    Uniform
)
from mirgecom.eos import (
    PyrometheusMixture,
    IdealSingleGas
)
from mirgecom.transport import SimpleTransport
from mirgecom.gas_model import GasModel
from arraycontext import thaw

from mirgecom.logging_quantities import (
    initialize_logmgr,
    logmgr_add_many_discretization_quantities,
    logmgr_add_cl_device_info,
    logmgr_add_device_memory_usage,
    set_sim_state
)

import cantera

logger = logging.getLogger(__name__)


class MyRuntimeError(RuntimeError):
    """Simple exception for fatal driver errors."""

    pass


# Box grid generator widget lifted from @majosm and slightly bent
def _get_box_mesh(dim, a, b, n, t=None, periodic=None):
    if periodic is None:
        periodic = (False)*dim

    dim_names = ["x", "y", "z"]
    bttf = {}
    for i in range(dim):
        bttf["-"+str(i+1)] = ["-"+dim_names[i]]
        bttf["+"+str(i+1)] = ["+"+dim_names[i]]
    from meshmode.mesh.generation import generate_regular_rect_mesh as gen
    return gen(a=a, b=b, n=n, boundary_tag_to_face=bttf, mesh_type=t,
               periodic=periodic)


@mpi_entry_point
def main(ctx_factory=cl.create_some_context, use_logmgr=True,
         use_leap=False, use_overintegration=False,
         use_profiling=False, casename=None, lazy=False,
         rst_filename=None, actx_class=PyOpenCLArrayContext,
         log_dependent=True):
    """Drive example."""
    cl_ctx = ctx_factory()

    if casename is None:
        casename = "mirgecom"

    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    nproc = comm.Get_size()

    from mirgecom.simutil import global_reduce as _global_reduce
    global_reduce = partial(_global_reduce, comm=comm)

    logmgr = initialize_logmgr(use_logmgr,
        filename=f"{casename}.sqlite", mode="wu", mpi_comm=comm)

    if use_profiling:
        queue = cl.CommandQueue(cl_ctx,
            properties=cl.command_queue_properties.PROFILING_ENABLE)
    else:
        queue = cl.CommandQueue(cl_ctx)

    if lazy:
        actx = actx_class(comm, queue, mpi_base_tag=12000,
                allocator=cl_tools.MemoryPool(cl_tools.ImmediateAllocator(queue)))
    else:
        actx = actx_class(comm, queue,
                allocator=cl_tools.MemoryPool(cl_tools.ImmediateAllocator(queue)),
                force_device_scalars=True)

    # if actx_class == PytatoPyOpenCLArrayContext:
    #     actx = actx_class(comm, queue, mpi_base_tag=12000)
    # else:
    #     # actx = actx_class(
    #     #    queue,
    #     #    allocator=cl_tools.MemoryPool(cl_tools.ImmediateAllocator(queue)))
    #     actx = actx_class(queue)

    # Some discretization parameters
    dim = 3
    # nel_1d = 8
    order = 1
    x_scale = 1
    y_scale = 1
    z_scale = 1
    chlen = .25
    domain_xlen = 1
    domain_ylen = 1
    domain_zlen = 1
    xsize = domain_xlen*x_scale
    ysize = domain_ylen*y_scale
    zsize = domain_zlen*z_scale
    ncx = int(xsize / chlen)
    ncy = int(ysize / chlen)
    ncz = int(zsize / chlen)
    x0 = xsize/2
    y0 = ysize/2
    z0 = zsize/2
    xleft = x0 - xsize/2
    xright = x0 + xsize/2
    ybottom = y0 - ysize/2
    ytop = y0 + ysize/2
    zback = z0 - zsize/2
    zfront = z0 + zsize/2

    # {{{ Time stepping control

    # This example runs only 3 steps by default (to keep CI ~short)
    # With the mixture defined below, equilibrium is achieved at ~40ms
    # To run to equilibrium, set t_final >= 40ms.

    # Time stepper selection
    if use_leap:
        from leap.rk import RK4MethodBuilder
        timestepper = RK4MethodBuilder("state")
    else:
        timestepper = rk4_step
        timestepper = euler_step

    # Time loop control parameters
    current_step = 0
    t_final = 2e-8
    current_cfl = 0.05
    current_dt = 1e-9
    current_t = 0
    constant_cfl = False

    # i.o frequencies
    nstatus = 100
    nviz = 100
    nhealth = 100
    nrestart = 1000
    simulation_run = False

    # }}}  Time stepping control

    grid_only = 0
    discr_only = 0
    inviscid_only = 0
    inert_only = 0
    single_gas_only = 0
    dummy_rhs_only = 0
    adiabatic_boundary = 0
    periodic_boundary = 1
    timestepping_on = 1

    init_temperature = 1500
    wall_temperature = init_temperature
    temperature_seed = init_temperature

    n_refine = 1
    periodic = (periodic_boundary == 1,)*dim
    npts_x = ncx * n_refine
    npts_y = ncy * n_refine
    npts_z = ncz * n_refine

    if dim == 1:
        npts_axis = (npts_x,)
        box_ll = (xleft,)
        box_ur = (xright,)
    elif dim == 2:
        npts_axis = (npts_x, npts_y)
        box_ll = (xleft, ybottom)
        box_ur = (xright, ytop)
    else:
        npts_axis = (npts_x, npts_y, npts_z)
        box_ll = (xleft, ybottom, zback)
        box_ur = (xright, ytop, zfront)

    if single_gas_only:
        inert_only = 1

    print(f"{grid_only=},{discr_only=},{inert_only=}")
    print(f"{single_gas_only=},{dummy_rhs_only=}")
    print(f"{periodic_boundary=},{adiabatic_boundary=}")
    print(f"{timestepping_on=}, {inviscid_only=}")

    debug = False

    rst_path = "restart_data/"
    rst_pattern = (
        rst_path + "{cname}-{step:04d}-{rank:04d}.pkl"
    )
    if rst_filename:  # read the grid from restart data
        rst_filename = f"{rst_filename}-{rank:04d}.pkl"

        from mirgecom.restart import read_restart_data
        restart_data = read_restart_data(actx, rst_filename)
        local_mesh = restart_data["local_mesh"]
        local_nelements = local_mesh.nelements
        global_nelements = restart_data["global_nelements"]
        assert restart_data["num_parts"] == nproc
        rst_time = restart_data["t"]
        rst_step = restart_data["step"]
        rst_order = restart_data["order"]
    else:  # generate the grid from scratch
        generate_mesh = partial(_get_box_mesh, dim, a=box_ll, b=box_ur, n=npts_axis,
                                periodic=periodic)

        local_mesh, global_nelements = generate_and_distribute_mesh(comm,
                                                                    generate_mesh)
        local_nelements = local_mesh.nelements

    if grid_only:
        print(f"{rank=},{local_nelements=},{global_nelements=}")
        return 0

    from grudge.dof_desc import DISCR_TAG_BASE, DISCR_TAG_QUAD
    from meshmode.discretization.poly_element import \
        default_simplex_group_factory, QuadratureSimplexGroupFactory

    discr = EagerDGDiscretization(
        actx, local_mesh,
        discr_tag_to_group_factory={
            DISCR_TAG_BASE: default_simplex_group_factory(
                base_dim=local_mesh.dim, order=order),
            DISCR_TAG_QUAD: QuadratureSimplexGroupFactory(2*order + 1)
        },
        mpi_communicator=comm
    )
    nodes = thaw(discr.nodes(), actx)
    ones = discr.zeros(actx) + 1.0

    if use_overintegration:
        quadrature_tag = DISCR_TAG_QUAD
    else:
        quadrature_tag = None

    ones = discr.zeros(actx) + 1.0

    if discr_only:
        print(f"{rank=},{local_nelements=},{global_nelements=}")
        print(f"Discr: {nodes.shape=}")
        return 0

    vis_timer = None

    if logmgr:
        logmgr_add_cl_device_info(logmgr, queue)
        logmgr_add_device_memory_usage(logmgr, queue)

        vis_timer = IntervalTimer("t_vis", "Time spent visualizing")
        logmgr.add_quantity(vis_timer)

        logmgr.add_watches([
            ("step.max", "step = {value}, "),
            ("t_sim.max", "sim time: {value:1.6e} s\n"),
            ("t_step.max", "------- step walltime: {value:6g} s, "),
            ("t_log.max", "log walltime: {value:6g} s")
        ])

        if log_dependent:
            logmgr_add_many_discretization_quantities(logmgr, discr, dim,
                                                      extract_vars_for_logging,
                                                      units_for_logging)
            logmgr.add_watches([
                ("min_pressure", "\n------- P (min, max) (Pa) = ({value:1.9e}, "),
                ("max_pressure",    "{value:1.9e})\n"),
                ("min_temperature", "------- T (min, max) (K)  = ({value:7g}, "),
                ("max_temperature",    "{value:7g})\n")])

    if single_gas_only:
        nspecies = 0
        init_pressure = 101325
        init_density = 1.0
        init_y = 0
    else:
        # {{{  Set up initial state using Cantera

        # Use Cantera for initialization
        # -- Pick up a CTI for the thermochemistry config
        # --- Note: Users may add their own CTI file by dropping it into
        # ---       mirgecom/mechanisms alongside the other CTI files.
        from mirgecom.mechanisms import get_mechanism_cti
        mech_cti = get_mechanism_cti("uiuc")

        cantera_soln = cantera.Solution(phase_id="gas", source=mech_cti)
        nspecies = cantera_soln.n_species

        # Initial temperature, pressure, and mixutre mole fractions are needed
        # set up the initial state in Cantera.
        temperature_seed = 1500.0  # Initial temperature hot enough to burn
        # Parameters for calculating the amounts of fuel, oxidizer, and inert species
        equiv_ratio = 1.0
        ox_di_ratio = 0.21
        stoich_ratio = 3.0
        # Grab array indices for the specific species, ethylene, oxygen, and nitrogen
        i_fu = cantera_soln.species_index("C2H4")
        i_ox = cantera_soln.species_index("O2")
        i_di = cantera_soln.species_index("N2")
        x = np.zeros(nspecies)
        # Set the species mole fractions according to our desired fuel/air mixture
        x[i_fu] = (ox_di_ratio*equiv_ratio)/(stoich_ratio+ox_di_ratio*equiv_ratio)
        x[i_ox] = stoich_ratio*x[i_fu]/equiv_ratio
        x[i_di] = (1.0-ox_di_ratio)*x[i_ox]/ox_di_ratio
        # Uncomment next line to make pylint fail when it can't find cantera.one_atm
        one_atm = cantera.one_atm  # pylint: disable=no-member
        # one_atm = 101325.0

        # Let the user know about how Cantera is being initilized
        print(f"Input state (T,P,X) = ({temperature_seed}, {one_atm}, {x}")
        # Set Cantera internal gas temperature, pressure, and mole fractios
        cantera_soln.TPX = temperature_seed, one_atm, x
        # Pull temperature, total density, mass fractions, and pressure from Cantera
        # We need total density, mass fractions to initialize the fluid/gas state.
        can_t, can_rho, can_y = cantera_soln.TDY
        can_p = cantera_soln.P
        init_pressure = can_p
        init_density = can_rho
        init_temperature = can_t
        init_y = can_y
        print(f"Cantera state (rho,T,P,Y) = ({can_rho}, {can_t}, {can_p}, {can_y}")
        # *can_t*, *can_p* should not differ (much) from user's initial data,
        # but we want to ensure that we use the same starting point as Cantera,
        # so we use Cantera's version of these data.

        # }}}

    # {{{ Create Pyrometheus thermochemistry object & EOS

    # Create a Pyrometheus EOS with the Cantera soln. Pyrometheus uses Cantera and
    # generates a set of methods to calculate chemothermomechanical properties and
    # states for this particular mechanism.
    if inert_only or single_gas_only:
        eos = IdealSingleGas()
    else:
        from mirgecom.thermochemistry import make_pyrometheus_mechanism_class
        pyro_mechanism = make_pyrometheus_mechanism_class(cantera_soln)(actx.np)
        eos = PyrometheusMixture(pyro_mechanism, temperature_guess=temperature_seed)

    # {{{ Initialize simple transport model

    kappa = 10
    spec_diffusivity = 0 * np.ones(nspecies)
    sigma = 1e-5
    if inviscid_only:
        transport_model = None
        gas_model = GasModel(eos=eos)
    else:
        transport_model = SimpleTransport(viscosity=sigma,
                                          thermal_conductivity=kappa,
                                          species_diffusivity=spec_diffusivity)
        gas_model = GasModel(eos=eos, transport=transport_model)

    # }}}

    from pytools.obj_array import make_obj_array

    if inert_only:
        compute_temperature_update = None
    else:
        def get_temperature_update(cv, temperature):
            y = cv.species_mass_fractions
            e = gas_model.eos.internal_energy(cv) / cv.mass
            return pyro_mechanism.get_temperature_update_energy(e, temperature, y)
        compute_temperature_update = actx.compile(get_temperature_update)

    from mirgecom.gas_model import make_fluid_state

    def get_fluid_state(cv, tseed):
        return make_fluid_state(cv=cv, gas_model=gas_model,
                                temperature_seed=tseed)

    construct_fluid_state = actx.compile(get_fluid_state)

    # }}}

    # {{{ MIRGE-Com state initialization

    # Initialize the fluid/gas state with Cantera-consistent data:
    # (density, pressure, temperature, mass_fractions)
    velocity = np.zeros(shape=(dim,))
    if single_gas_only or inert_only:
        initializer = Uniform(dim=dim, p=init_pressure, rho=init_density,
                              velocity=velocity, nspecies=nspecies)
    else:
        initializer = MixtureInitializer(dim=dim, nspecies=nspecies,
                                         pressure=init_pressure,
                                         temperature=init_temperature,
                                         massfractions=init_y, velocity=velocity)

    def _boundary_state_func(discr, btag, gas_model, actx, init_func, **kwargs):
        bnd_discr = discr.discr_from_dd(btag)
        nodes = thaw(bnd_discr.nodes(), actx)
        return make_fluid_state(init_func(x_vec=nodes, eos=gas_model.eos,
                                          **kwargs), gas_model)

    # def quiescent(x_vec, eos, cv=None, **kwargs):
    #    x = x_vec[0]
    #    zeros = 0*x
    #    rho = zeros + 1
    #    velocity = make_obj_array([zeros for _ in range(dim)])
    #    mom = rho*velocity
    #    gamma = eos.gamma(cv)
    #    rhoe = zeros + base_pressure / (gamma - 1)

    #    return make_conserved(dim=dim, mass=rho, energy=rhoe,
    #                          momentum=mom)

    # initializer = quiescent
    # exact = initializer(x_vec=nodes, eos=gas_model.eos)

    # def _boundary_solution(discr, btag, gas_model, state_minus, **kwargs):
    #     actx = state_minus.array_context
    #     bnd_discr = discr.discr_from_dd(btag)
    #     nodes = thaw(bnd_discr.nodes(), actx)
    #    return make_fluid_state(initializer(x_vec=nodes, eos=gas_model.eos,
    #                                        cv=state_minus.cv, **kwargs), gas_model)

    #    boundaries = {DTAG_BOUNDARY("-1"):
    #                  PrescribedFluidBoundary(boundary_state_func=_boundary_solution),
    #                  DTAG_BOUNDARY("+1"):
    #                  PrescribedFluidBoundary(boundary_state_func=_boundary_solution),
    #                  DTAG_BOUNDARY("-2"): AdiabaticNoslipMovingBoundary(),
    #                  DTAG_BOUNDARY("+2"): AdiabaticNoslipMovingBoundary()}

    from mirgecom.boundary import (
        AdiabaticNoslipWallBoundary,
        IsothermalWallBoundary
    )
    adiabatic_wall = AdiabaticNoslipWallBoundary()
    isothermal_wall = IsothermalWallBoundary(wall_temperature=wall_temperature)
    if adiabatic_boundary:
        wall = adiabatic_wall
    else:
        wall = isothermal_wall

    if periodic_boundary:
        boundaries = {}  # For periodic, also set above in meshgen
    else:
        boundaries = {BTAG_ALL: wall}

    if rst_filename:
        current_step = rst_step
        current_t = rst_time
        if logmgr:
            from mirgecom.logging_quantities import logmgr_set_time
            logmgr_set_time(logmgr, current_step, current_t)
        if order == rst_order:
            current_cv = restart_data["cv"]
            temperature_seed = restart_data["temperature_seed"]
        else:
            rst_cv = restart_data["cv"]
            old_discr = EagerDGDiscretization(actx, local_mesh, order=rst_order,
                                              mpi_communicator=comm)
            from meshmode.discretization.connection import make_same_mesh_connection
            connection = make_same_mesh_connection(actx, discr.discr_from_dd("vol"),
                                                   old_discr.discr_from_dd("vol"))
            current_cv = connection(rst_cv)
            temperature_seed = connection(restart_data["temperature_seed"])
    else:
        # Set the current state from time 0
        current_cv = initializer(eos=gas_model.eos, x_vec=nodes)
        temperature_seed = temperature_seed * ones

    # The temperature_seed going into this function is:
    # - At time 0: the initial temperature input data (maybe from Cantera)
    # - On restart: the restarted temperature seed from restart file (saving
    #               the *seed* allows restarts to be deterministic
    current_fluid_state = construct_fluid_state(current_cv, temperature_seed)
    current_dv = current_fluid_state.dv
    temperature_seed = current_dv.temperature

    # Inspection at physics debugging time
    if debug:
        print("Initial MIRGE-Com state:")
        print(f"Initial DV pressure: {current_fluid_state.pressure}")
        print(f"Initial DV temperature: {current_fluid_state.temperature}")

    # }}}

    visualizer = make_visualizer(discr)
    initname = initializer.__class__.__name__
    eosname = gas_model.eos.__class__.__name__
    init_message = make_init_message(dim=dim, order=order,
                                     nelements=local_nelements,
                                     global_nelements=global_nelements,
                                     dt=current_dt, t_final=t_final, nstatus=nstatus,
                                     nviz=nviz, cfl=current_cfl,
                                     constant_cfl=constant_cfl, initname=initname,
                                     eosname=eosname, casename=casename)

    if inert_only == 0:
        # Cantera equilibrate calculates the expected end
        # state @ chemical equilibrium
        # i.e. the expected state after all reactions
        cantera_soln.equilibrate("UV")
        eq_temperature, eq_density, eq_mass_fractions = cantera_soln.TDY
        eq_pressure = cantera_soln.P

        # Report the expected final state to the user
        if rank == 0:
            logger.info(init_message)
            logger.info(f"Expected equilibrium state:"
                        f" {eq_pressure=}, {eq_temperature=},"
                        f" {eq_density=}, {eq_mass_fractions=}")

    def my_write_status(dt, cfl, dv=None):
        status_msg = f"------ {dt=}" if constant_cfl else f"----- {cfl=}"
        if ((dv is not None) and (not log_dependent)):

            temp = dv.temperature
            press = dv.pressure

            from grudge.op import nodal_min_loc, nodal_max_loc
            tmin = global_reduce(actx.to_numpy(nodal_min_loc(discr, "vol", temp)),
                                 op="min")
            tmax = global_reduce(actx.to_numpy(nodal_max_loc(discr, "vol", temp)),
                                 op="max")
            pmin = global_reduce(actx.to_numpy(nodal_min_loc(discr, "vol", press)),
                                 op="min")
            pmax = global_reduce(actx.to_numpy(nodal_max_loc(discr, "vol", press)),
                                 op="max")
            dv_status_msg = f"\nP({pmin}, {pmax}), T({tmin}, {tmax})"
            status_msg = status_msg + dv_status_msg

        if rank == 0:
            logger.info(status_msg)

    def my_write_viz(step, t, dt, cv, ts_field, dv):
        viz_fields = [("cv", cv), ("dv", dv),
                      ("dt" if constant_cfl else "cfl", ts_field)]
        write_visfile(discr, viz_fields, visualizer, vizname=casename,
                      step=step, t=t, overwrite=True, vis_timer=vis_timer)

    def my_write_restart(step, t, state, temperature_seed):
        rst_fname = rst_pattern.format(cname=casename, step=step, rank=rank)
        if rst_fname == rst_filename:
            if rank == 0:
                logger.info("Skipping overwrite of restart file.")
        else:
            rst_data = {
                "local_mesh": local_mesh,
                "cv": state.cv,
                "temperature_seed": temperature_seed,
                "t": t,
                "step": step,
                "order": order,
                "global_nelements": global_nelements,
                "num_parts": nproc
            }
            from mirgecom.restart import write_restart_file
            write_restart_file(actx, rst_data, rst_fname, comm)

    def my_health_check(cv, dv):
        import grudge.op as op
        health_error = False

        pressure = dv.pressure
        temperature = dv.temperature

        from mirgecom.simutil import check_naninf_local
        if check_naninf_local(discr, "vol", pressure):
            health_error = True
            logger.info(f"{rank=}: Invalid pressure data found.")

        if check_naninf_local(discr, "vol", temperature):
            health_error = True
            logger.info(f"{rank=}: Invalid temperature data found.")

        if inert_only == 0:
            # This check is the temperature convergence check
            temp_resid = compute_temperature_update(cv, temperature) / temperature
            temp_err = (actx.to_numpy(op.nodal_max_loc(discr, "vol", temp_resid)))
            if temp_err > 1e-8:
                health_error = True
                logger.info(f"{rank=}: Temperature is not converged {temp_resid=}.")

        return health_error

    from mirgecom.viscous import (
        get_viscous_timestep,
        get_viscous_cfl
    )

    def get_dt(state):
        return get_viscous_timestep(discr, state=state)

    compute_dt = actx.compile(get_dt)

    def get_cfl(state, dt):
        return get_viscous_cfl(discr, dt=dt, state=state)

    compute_cfl = actx.compile(get_cfl)

    # compute_production_rates = None
    # if inert_only == 0:
    #
    #    def get_production_rates(cv, temperature):
    #        return eos.get_production_rates(cv, temperature)
    #
    #    compute_production_rates = actx.compile(get_production_rates)

    def my_get_timestep(t, dt, state):
        #  richer interface to calculate {dt,cfl} returns node-local estimates
        t_remaining = max(0, t_final - t)

        if constant_cfl:
            ts_field = current_cfl * compute_dt(state)
            from grudge.op import nodal_min_loc
            dt = global_reduce(actx.to_numpy(nodal_min_loc(discr, "vol", ts_field)),
                               op="min")
            cfl = current_cfl
        else:
            ts_field = compute_cfl(state, current_dt)
            from grudge.op import nodal_max_loc
            cfl = global_reduce(actx.to_numpy(nodal_max_loc(discr, "vol", ts_field)),
                                op="max")
        return ts_field, cfl, min(t_remaining, dt)

    def my_pre_step(step, t, dt, state):
        cv, tseed = state
        fluid_state = construct_fluid_state(cv, tseed)
        dv = fluid_state.dv
        # ns_rhs, grad_cv, grad_t = ns_operator(discr, state=fluid_state, time=t,
        #                                       boundaries=boundaries,
        #                                       gas_model=gas_model,
        #                                       quadrature_tag=quadrature_tag,
        #                                       return_gradients=True)

        # euler_rhs = euler_operator(discr, state=fluid_state, time=t,
        #                            boundaries=boundaries, gas_model=gas_model,
        #                            quadrature_tag=quadrature_tag)
        # chem_rhs = eos.get_species_source_terms(cv, fluid_state.temperature)

        try:

            if logmgr:
                logmgr.tick_before()

            if simulation_run:
                from mirgecom.simutil import check_step
                do_viz = check_step(step=step, interval=nviz)
                do_restart = check_step(step=step, interval=nrestart)
                do_health = check_step(step=step, interval=nhealth)
                do_status = check_step(step=step, interval=nstatus)

                if do_health:
                    health_errors = global_reduce(my_health_check(cv, dv), op="lor")
                    if health_errors:
                        if rank == 0:
                            logger.info("Fluid solution failed health check.")
                        raise MyRuntimeError("Failed simulation health check.")

                ts_field, cfl, dt = my_get_timestep(t=t, dt=dt, state=fluid_state)

                if do_status:
                    my_write_status(dt=dt, cfl=cfl, dv=dv)

                if do_restart:
                    my_write_restart(step=step, t=t, state=fluid_state,
                                 temperature_seed=tseed)

                if do_viz:
                    my_write_viz(step=step, t=t, dt=dt, cv=cv, dv=dv,
                                 ts_field=ts_field)

        except MyRuntimeError:
            if rank == 0:
                logger.info("Errors detected; attempting graceful exit.")
            # my_write_viz(step=step, t=t, dt=dt, state=cv)
            # my_write_restart(step=step, t=t, state=fluid_state)
            raise

        return state, dt

    def my_post_step(step, t, dt, state):
        cv, tseed = state
        # fluid_state = construct_fluid_state(cv, tseed)

        # Logmgr needs to know about EOS, dt, dim?
        # imo this is a design/scope flaw
        if logmgr:
            set_dt(logmgr, dt)
            if log_dependent:
                set_sim_state(logmgr, dim, cv, gas_model.eos)
            logmgr.tick_after()

        return state, dt

    from mirgecom.inviscid import inviscid_flux_rusanov

    def cfd_rhs(t, state):
        cv, tseed = state
        from mirgecom.gas_model import make_fluid_state
        fluid_state = make_fluid_state(cv=cv, gas_model=gas_model,
                                       temperature_seed=tseed)
        if inviscid_only:
            fluid_rhs = \
                euler_operator(discr, state=fluid_state, time=t,
                               boundaries=boundaries, gas_model=gas_model,
                               inviscid_numerical_flux_func=inviscid_flux_rusanov,
                               quadrature_tag=quadrature_tag)
        else:
            fluid_rhs = \
                ns_operator(discr, state=fluid_state, time=t, boundaries=boundaries,
                            gas_model=gas_model, quadrature_tag=quadrature_tag,
                            inviscid_numerical_flux_func=inviscid_flux_rusanov)

        if inert_only:
            chem_rhs = 0*fluid_rhs
        else:
            chem_rhs = eos.get_species_source_terms(cv, fluid_state.temperature)

        fluid_rhs = fluid_rhs + chem_rhs
        tseed_rhs = 0*tseed
        return make_obj_array([fluid_rhs, tseed_rhs])

    def dummy_rhs(t, state):
        cv, tseed = state
        return make_obj_array([0*cv, 0*tseed])

    if dummy_rhs_only:
        my_rhs = dummy_rhs
    else:
        my_rhs = cfd_rhs

    current_dt = get_sim_timestep(discr, current_fluid_state, current_t, current_dt,
                                  current_cfl, t_final, constant_cfl)

    current_state = make_obj_array([current_cv, temperature_seed])

    if timestepping_on:
        if rank == 0:
            print(f"Timestepping: {current_step=}, {current_t=}, {t_final=},"
                  f" {current_dt=}")

        current_step, current_t, current_state = \
            advance_state(rhs=my_rhs, timestepper=timestepper,
                          pre_step_callback=my_pre_step, istep=current_step,
                          post_step_callback=my_post_step, dt=current_dt,
                          state=make_obj_array([current_cv, temperature_seed]),
                          t=current_t, t_final=t_final)

    # Dump the final data
    if rank == 0:
        logger.info("Checkpointing final state ...")

    final_cv, tseed = current_state
    final_fluid_state = construct_fluid_state(final_cv, tseed)
    final_dv = final_fluid_state.dv
    # final_dm = compute_production_rates(final_cv, final_dv.temperature)
    ts_field, cfl, dt = my_get_timestep(t=current_t, dt=current_dt,
                                        state=final_fluid_state)

    # ns_rhs, grad_cv, grad_t = ns_operator(discr, state=final_fluid_state,
    #                                       time=current_t,
    #                                       boundaries=boundaries,
    #                                       gas_model=gas_model,
    #                                       quadrature_tag=quadrature_tag,
    #                                       return_gradients=True)

    # euler_rhs = euler_operator(discr, state=final_fluid_state, time=current_t,
    #             boundaries=boundaries, gas_model=gas_model,
    #                           quadrature_tag=quadrature_tag)
    # chem_rhs=eos.get_species_source_terms(final_cv, final_fluid_state.temperature)
    my_write_viz(step=current_step, t=current_t, dt=dt, cv=final_cv, dv=final_dv,
                 ts_field=ts_field)
    my_write_status(dt=dt, cfl=cfl, dv=final_dv)
    my_write_restart(step=current_step, t=current_t, state=final_fluid_state,
                     temperature_seed=tseed)

    if logmgr:
        logmgr.close()
    elif use_profiling:
        print(actx.tabulate_profiling_data())

    finish_tol = 1e-16
    assert np.abs(current_t - t_final) < finish_tol

    health_errors = global_reduce(my_health_check(cv=final_cv, dv=final_dv),
                                  op="lor")
    if health_errors:
        if rank == 0:
            logger.info("Fluid solution failed health check.")
        raise MyRuntimeError("Failed simulation health check.")


if __name__ == "__main__":
    import argparse
    casename = "combozzle"
    parser = argparse.ArgumentParser(description=f"MIRGE-Com Example: {casename}")
    parser.add_argument("--overintegration", action="store_true",
        help="use overintegration in the RHS computations")
    parser.add_argument("--lazy", action="store_true",
        help="switch to a lazy computation mode")
    parser.add_argument("--profiling", action="store_true",
        help="turn on detailed performance profiling")
    parser.add_argument("--log", action="store_true", default=True,
        help="turn on logging")
    parser.add_argument("--leap", action="store_true",
        help="use leap timestepper")
    parser.add_argument("--restart_file", help="root name of restart file")
    parser.add_argument("--casename", help="casename to use for i/o")
    args = parser.parse_args()
    from warnings import warn
    warn("Automatically turning off DV logging. MIRGE-Com Issue(578)")
    lazy = args.lazy
    log_dependent = False
    if args.profiling:
        if lazy:
            raise ValueError("Can't use lazy and profiling together.")

    from grudge.array_context import get_reasonable_array_context_class
    actx_class = get_reasonable_array_context_class(lazy=lazy, distributed=True)

    logging.basicConfig(format="%(message)s", level=logging.INFO)
    if args.casename:
        casename = args.casename
    rst_filename = None
    if args.restart_file:
        rst_filename = args.restart_file

    main(use_logmgr=args.log, use_leap=args.leap,
         use_overintegration=args.overintegration,
         use_profiling=args.profiling, lazy=lazy,
         casename=casename, rst_filename=rst_filename, actx_class=actx_class,
         log_dependent=log_dependent)

# vim: foldmethod=marker
