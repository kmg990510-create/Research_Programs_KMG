"""Standard internal data models for MoS2_adsorption_sim (no Streamlit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ase import Atoms

from ads_core.config import Config

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

DEFECT_PRISTINE = "pristine"
DEFECT_VS = "V_S"
DEFECT_VS2 = "V_S2"
VALID_DEFECT_TYPES = (DEFECT_PRISTINE, DEFECT_VS, DEFECT_VS2)

SITE_MO_TOP = "Mo_top"
SITE_S_TOP = "S_top"
SITE_HOLLOW = "Hollow"
SITE_BRIDGE = "Bridge"
SITE_VS = "V_S"
SITE_VS2 = "V_S2"
SITE_VS_RIM = "V_S_rim"

ORIENTATION_FLAT = "flat"
ORIENTATION_ANCHOR_DOWN = "anchor_down"
ORIENTATION_ANCHOR_UP = "anchor_up"
VALID_ORIENTATIONS = (ORIENTATION_FLAT, ORIENTATION_ANCHOR_DOWN, ORIENTATION_ANCHOR_UP)

STATUS_VALID = "valid"
STATUS_ATTENTION = "attention"
STATUS_INVALID = "invalid"
STATUS_ORDER = (STATUS_VALID, STATUS_ATTENTION, STATUS_INVALID)

VALID_BACKENDS = ("mace_mp", "mattersim", "synth_morse")
VALID_OPTIMIZERS = ("BFGS", "LBFGS", "FIRE")


@dataclass(frozen=True)
class WarningRecord:
    """One quality or build warning. ``code`` names the cause; ``message`` is for people."""

    code: str
    message: str
    target_id: str
    severity: str = SEVERITY_WARNING
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SlabSettings:
    """Settings read from ``config.yaml`` under ``slab``."""

    substrate: str
    substrate_candidates: tuple[str, ...]
    supported_substrates: tuple[str, ...]
    lattice_a_A: float
    s_s_thickness_A: float
    supercell_nx: int
    supercell_ny: int
    supercell_min_n: int
    supercell_max_n: int
    vacuum_A: float
    defect_type: str
    fix_bottom_layer: bool
    layer_tolerance_A: float

    def __post_init__(self) -> None:
        if not self.lattice_a_A > 0 or not self.s_s_thickness_A > 0:
            raise ValueError("lattice_a_A and s_s_thickness_A must be positive")
        if self.supercell_min_n < 1 or self.supercell_max_n < self.supercell_min_n:
            raise ValueError("supercell_min_n must be >= 1 and <= supercell_max_n")
        if self.supercell_nx < 1 or self.supercell_ny < 1:
            raise ValueError("supercell dimensions must be >= 1")
        if not self.vacuum_A > 0:
            raise ValueError("vacuum_A must be positive")
        if not self.substrate_candidates or not self.supported_substrates:
            raise ValueError("substrate_candidates and supported_substrates must not be empty")
        if self.substrate not in self.supported_substrates:
            raise ValueError(f"Unsupported substrate {self.substrate!r}; expected one of {self.supported_substrates}")
        if not all(item in self.substrate_candidates for item in self.supported_substrates):
            raise ValueError("supported_substrates must be a subset of substrate_candidates")
        if self.defect_type not in VALID_DEFECT_TYPES:
            raise ValueError(f"Unsupported defect_type {self.defect_type!r}; expected one of {VALID_DEFECT_TYPES}")

    @classmethod
    def from_config(cls, config: Config) -> "SlabSettings":
        return cls(
            substrate=config.text("slab.substrate"),
            substrate_candidates=tuple(config.text_list("slab.substrate_candidates")),
            supported_substrates=tuple(config.text_list("slab.supported_substrates")),
            lattice_a_A=config.number("slab.lattice_a_A"),
            s_s_thickness_A=config.number("slab.s_s_thickness_A"),
            supercell_nx=config.integer("slab.supercell_nx"),
            supercell_ny=config.integer("slab.supercell_ny"),
            supercell_min_n=config.integer("slab.supercell_min_n"),
            supercell_max_n=config.integer("slab.supercell_max_n"),
            vacuum_A=config.number("slab.vacuum_A"),
            defect_type=config.text("slab.defect_type"),
            fix_bottom_layer=config.boolean("slab.fix_bottom_layer"),
            layer_tolerance_A=config.number("slab.layer_tolerance_A"),
        )


@dataclass(frozen=True)
class MoleculeSettings:
    """Settings read from ``config.yaml`` under ``molecules``."""

    vacuum_box_A: float
    covalent_bond_scale: float
    min_internal_distance_A: float
    presets: tuple[str, ...]
    tma_al_c_bond_A: float
    tma_c_h_bond_A: float
    tma_h_c_h_angle_deg: float

    def __post_init__(self) -> None:
        if not self.vacuum_box_A > 0:
            raise ValueError("vacuum_box_A must be positive")
        if not self.covalent_bond_scale > 0:
            raise ValueError("covalent_bond_scale must be positive")
        if not self.min_internal_distance_A > 0:
            raise ValueError("min_internal_distance_A must be positive")

    @classmethod
    def from_config(cls, config: Config) -> "MoleculeSettings":
        return cls(
            vacuum_box_A=config.number("molecules.vacuum_box_A"),
            covalent_bond_scale=config.number("molecules.covalent_bond_scale"),
            min_internal_distance_A=config.number("molecules.min_internal_distance_A"),
            presets=tuple(config.text_list("molecules.presets")),
            tma_al_c_bond_A=config.number("molecules.tma.al_c_bond_A"),
            tma_c_h_bond_A=config.number("molecules.tma.c_h_bond_A"),
            tma_h_c_h_angle_deg=config.number("molecules.tma.h_c_h_angle_deg"),
        )


@dataclass(frozen=True)
class PoseSettings:
    """Settings read from ``config.yaml`` under ``poses``."""

    site_search_height_A: float
    site_symm_reduce: float
    site_match_tolerance_A: float
    initial_heights_A: tuple[float, ...]
    orientations: tuple[str, ...]
    azimuth_angles_deg: tuple[float, ...]
    azimuth_candidates_deg: tuple[float, ...]
    min_initial_distance_A: float
    defect_initial_height_A: float
    defect_rim_radius_A: float

    def __post_init__(self) -> None:
        for ori in self.orientations:
            if ori not in VALID_ORIENTATIONS:
                raise ValueError(f"Unsupported orientation {ori!r}; expected one of {VALID_ORIENTATIONS}")
        if not self.initial_heights_A:
            raise ValueError("initial_heights_A must not be empty")
        if not self.azimuth_candidates_deg:
            raise ValueError("azimuth_candidates_deg must not be empty")
        if not self.min_initial_distance_A > 0:
            raise ValueError("min_initial_distance_A must be positive")
        if not self.defect_rim_radius_A > 0:
            raise ValueError("defect_rim_radius_A must be positive")

    @classmethod
    def from_config(cls, config: Config) -> "PoseSettings":
        return cls(
            site_search_height_A=config.number("poses.site_search_height_A"),
            site_symm_reduce=config.number("poses.site_symm_reduce"),
            site_match_tolerance_A=config.number("poses.site_match_tolerance_A"),
            initial_heights_A=tuple(config.number_list("poses.initial_heights_A")),
            orientations=tuple(config.text_list("poses.orientations")),
            azimuth_angles_deg=tuple(config.number_list("poses.azimuth_angles_deg")),
            azimuth_candidates_deg=tuple(config.number_list("poses.azimuth_candidates_deg")),
            min_initial_distance_A=config.number("poses.min_initial_distance_A"),
            defect_initial_height_A=config.number("poses.defect_initial_height_A"),
            defect_rim_radius_A=config.number("poses.defect_rim_radius_A"),
        )


@dataclass(frozen=True, eq=False)
class SlabSpec:
    """Standard internal representation of a 2H-MoS2 slab."""

    surface_id: str
    supercell: tuple[int, int]
    defect_type: str
    vacuum_A: float
    fix_bottom_layer: bool
    lattice_a_A: float
    s_s_thickness_A: float
    top_s_z_A: float
    mo_z_A: float
    bottom_s_z_A: float
    defect_positions_A: tuple[tuple[float, float, float], ...]
    atoms: Atoms


@dataclass(frozen=True, eq=False)
class MoleculeSpec:
    """Standard internal representation of an isolated adsorbate molecule."""

    molecule_id: str
    formula: str
    source: str  # "preset" or "file"
    box_size_A: float
    anchor_index: int
    reference_bonds: tuple[tuple[int, int, float], ...]
    atoms: Atoms


@dataclass(frozen=True)
class AdsorptionSite:
    """One candidate lateral adsorption site on the slab."""

    site_type: str
    xy_A: tuple[float, float]
    ref_z_A: float
    source: str  # "pymatgen" or "defect"


@dataclass(frozen=True, eq=False)
class PoseSpec:
    """One initial slab + molecule configuration ready for relaxation."""

    pose_id: str
    surface_id: str
    molecule_id: str
    site_type: str
    site_xy_A: tuple[float, float]
    orientation: str
    azimuth_deg: float
    initial_height_A: float
    atoms: Atoms
    slab_indices: tuple[int, ...]
    mol_indices: tuple[int, ...]


@dataclass(frozen=True)
class CalculatorSettings:
    """Settings read from ``config.yaml`` under ``calculator``."""

    backend: str
    device: str
    mace_model: str
    mace_dtype: str
    mattersim_load_path: str
    d3_enabled: bool
    d3_xc: str
    d3_damping: str
    d3_cutoff_bohr: float
    synth_mo_s_de_eV: float
    synth_mo_s_r0_A: float
    synth_mo_adsorbate_de_eV: float
    synth_mo_adsorbate_r0_A: float
    synth_s_repulsion_eV: float
    synth_d3_c6_eV_A6: float
    synth_d3_damp_r0_A: float

    def __post_init__(self) -> None:
        if self.backend not in VALID_BACKENDS:
            raise ValueError(f"Unsupported backend {self.backend!r}; expected one of {VALID_BACKENDS}")
        if not self.d3_cutoff_bohr > 0:
            raise ValueError("d3_cutoff_bohr must be positive")

    @classmethod
    def from_config(cls, config: Config) -> "CalculatorSettings":
        return cls(
            backend=config.text("calculator.backend"),
            device=config.text("calculator.device"),
            mace_model=config.text("calculator.mace_model"),
            mace_dtype=config.text("calculator.mace_dtype"),
            mattersim_load_path=config.text("calculator.mattersim_load_path"),
            d3_enabled=config.boolean("calculator.d3.enabled"),
            d3_xc=config.text("calculator.d3.xc"),
            d3_damping=config.text("calculator.d3.damping"),
            d3_cutoff_bohr=config.number("calculator.d3.cutoff_bohr"),
            synth_mo_s_de_eV=config.number("calculator.synth.mo_s_de_eV"),
            synth_mo_s_r0_A=config.number("calculator.synth.mo_s_r0_A"),
            synth_mo_adsorbate_de_eV=config.number("calculator.synth.mo_adsorbate_de_eV"),
            synth_mo_adsorbate_r0_A=config.number("calculator.synth.mo_adsorbate_r0_A"),
            synth_s_repulsion_eV=config.number("calculator.synth.s_repulsion_eV"),
            synth_d3_c6_eV_A6=config.number("calculator.synth.d3_c6_eV_A6"),
            synth_d3_damp_r0_A=config.number("calculator.synth.d3_damp_r0_A"),
        )


@dataclass(frozen=True)
class RelaxationSettings:
    """Settings read from ``config.yaml`` under ``relaxation``."""

    optimizer: str
    fmax_eV_per_A: float
    max_steps: int
    trajectory_stride: int
    scan_heights_A: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.optimizer not in VALID_OPTIMIZERS:
            raise ValueError(f"Unsupported optimizer {self.optimizer!r}; expected one of {VALID_OPTIMIZERS}")
        if not self.fmax_eV_per_A > 0 or self.max_steps < 1:
            raise ValueError("fmax_eV_per_A must be positive and max_steps >= 1")
        if self.trajectory_stride < 1:
            raise ValueError("trajectory_stride must be >= 1")

    @classmethod
    def from_config(cls, config: Config) -> "RelaxationSettings":
        return cls(
            optimizer=config.text("relaxation.optimizer"),
            fmax_eV_per_A=config.number("relaxation.fmax_eV_per_A"),
            max_steps=config.integer("relaxation.max_steps"),
            trajectory_stride=config.integer("relaxation.trajectory_stride"),
            scan_heights_A=tuple(config.number_list("relaxation.scan_heights_A")),
        )


@dataclass(frozen=True)
class MdSettings:
    """Settings read from ``config.yaml`` under ``md``."""

    enabled: bool
    temperature_K: float
    timestep_fs: float
    steps: int
    friction_per_fs: float
    trajectory_stride: int
    adsorption_cutoff_A: float
    seed: int

    def __post_init__(self) -> None:
        if not self.temperature_K > 0:
            raise ValueError("md.temperature_K must be positive")
        if not self.timestep_fs > 0:
            raise ValueError("md.timestep_fs must be positive")
        if self.steps < 1:
            raise ValueError("md.steps must be >= 1")
        if not self.friction_per_fs > 0:
            raise ValueError("md.friction_per_fs must be positive")
        if self.trajectory_stride < 1:
            raise ValueError("md.trajectory_stride must be >= 1")
        if not self.adsorption_cutoff_A > 0:
            raise ValueError("md.adsorption_cutoff_A must be positive")
        if self.seed < 0:
            raise ValueError("md.seed must be >= 0")

    @classmethod
    def from_config(cls, config: Config) -> "MdSettings":
        return cls(
            enabled=config.boolean("md.enabled"),
            temperature_K=config.number("md.temperature_K"),
            timestep_fs=config.number("md.timestep_fs"),
            steps=config.integer("md.steps"),
            friction_per_fs=config.number("md.friction_per_fs"),
            trajectory_stride=config.integer("md.trajectory_stride"),
            adsorption_cutoff_A=config.number("md.adsorption_cutoff_A"),
            seed=config.integer("md.seed"),
        )


@dataclass(frozen=True)
class QualitySettings:
    """Settings read from ``config.yaml`` under ``quality``."""

    min_allowed_distance_A: float
    max_adsorption_distance_A: float
    max_slab_rmsd_invalid_A: float
    max_slab_rmsd_warn_A: float
    max_slab_def_warn_eV: float
    bond_stretch_warn_pct: float
    migration_threshold_A: float
    chemisorption_threshold_eV: float
    physisorption_threshold_eV: float

    @classmethod
    def from_config(cls, config: Config) -> "QualitySettings":
        return cls(
            min_allowed_distance_A=config.number("quality.min_allowed_distance_A"),
            max_adsorption_distance_A=config.number("quality.max_adsorption_distance_A"),
            max_slab_rmsd_invalid_A=config.number("quality.max_slab_rmsd_invalid_A"),
            max_slab_rmsd_warn_A=config.number("quality.max_slab_rmsd_warn_A"),
            max_slab_def_warn_eV=config.number("quality.max_slab_def_warn_eV"),
            bond_stretch_warn_pct=config.number("quality.bond_stretch_warn_pct"),
            migration_threshold_A=config.number("quality.migration_threshold_A"),
            chemisorption_threshold_eV=config.number("quality.chemisorption_threshold_eV"),
            physisorption_threshold_eV=config.number("quality.physisorption_threshold_eV"),
        )


@dataclass(frozen=True)
class ReportSettings:
    """Settings read from ``config.yaml`` under ``report``."""

    boltzmann_temp_K: float

    def __post_init__(self) -> None:
        if not self.boltzmann_temp_K > 0:
            raise ValueError("boltzmann_temp_K must be positive")

    @classmethod
    def from_config(cls, config: Config) -> "ReportSettings":
        return cls(boltzmann_temp_K=config.number("report.boltzmann_temp_K"))


@dataclass
class PoseBuildResult:
    poses: list[PoseSpec] = field(default_factory=list)
    sites: list[AdsorptionSite] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)


@dataclass(frozen=True)
class PoseResult:
    """Evaluated adsorption metrics and quality verdict for one pose."""

    pose_id: str
    surface_id: str
    defect_type: str
    molecule_id: str
    site_type: str
    orientation: str
    azimuth_deg: float
    initial_height_A: float
    calculator_id: str
    d3_enabled: bool
    converged: bool
    n_steps: int
    fmax_final_eV_per_A: float | None
    e_ads_eV: float | None
    e_ads_umlip_eV: float | None
    e_ads_d3_eV: float | None
    vdw_fraction: float | None
    e_int_eV: float | None
    e_def_slab_eV: float | None
    e_def_mol_eV: float | None
    d_min_A: float | None
    d_min_pair: str | None
    dz_com_A: float | None
    lateral_shift_A: float | None
    tilt_deg: float | None
    max_bond_stretch_pct: float | None
    slab_rmsd_A: float | None
    status: str
    reasons: tuple[str, ...]
    warnings: tuple[WarningRecord, ...] = ()

