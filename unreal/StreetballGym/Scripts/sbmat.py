"""Shared headless material-building helpers (used by make_court_materials.py, make_niagara_fx.py, import_env_assets.py,
build_grandma_extras.py). Substrate is on for this project (r.Substrate=True): hero materials wire Substrate Slab BSDFs
into the Front Material; simple materials use the classic pins, which Substrate converts automatically."""
import unreal

MEL = unreal.MaterialEditingLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


def new_material(path, blend=unreal.BlendMode.BLEND_OPAQUE, shading=unreal.MaterialShadingModel.MSM_DEFAULT_LIT, two_sided=False):
    pkg, name = path.rsplit("/", 1)
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = AT.create_asset(name, pkg, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("blend_mode", blend)
    m.set_editor_property("shading_model", shading)
    m.set_editor_property("two_sided", two_sided)
    return m


class Graph:
    def __init__(self, mat):
        self.m = mat
        self.x = -1400
        self.y = 0

    def e(self, cls, **props):
        node = MEL.create_material_expression(self.m, cls, self.x, self.y)
        self.y += 140
        if self.y > 2400:
            self.y = 0
            self.x += 320
        for k, v in props.items():
            node.set_editor_property(k, v)
        return node

    def const(self, v):
        return self.e(unreal.MaterialExpressionConstant, r=float(v))

    def const3(self, r, g, b):
        return self.e(unreal.MaterialExpressionConstant3Vector, constant=unreal.LinearColor(r, g, b, 1.0))

    def scalar(self, name, v):
        return self.e(unreal.MaterialExpressionScalarParameter, parameter_name=name, default_value=float(v))

    def vector(self, name, r, g, b, a=1.0):
        return self.e(unreal.MaterialExpressionVectorParameter, parameter_name=name, default_value=unreal.LinearColor(r, g, b, a))

    def custom(self, code, inputs, out_type=unreal.CustomMaterialOutputType.CMOT_FLOAT1, desc="Custom"):
        """inputs: list of (name, (expr, out_pin))."""
        node = self.e(unreal.MaterialExpressionCustom, code=code, output_type=out_type, description=desc)
        cis = []
        for n, _ in inputs:
            ci = unreal.CustomInput()
            ci.set_editor_property("input_name", n)
            cis.append(ci)
        node.set_editor_property("inputs", cis)
        for n, (src, pin) in inputs:
            self.link(src, pin, node, n)
        return node

    def link(self, a, a_out, b, b_in):
        ok = MEL.connect_material_expressions(a, a_out, b, b_in)
        if not ok:
            raise RuntimeError(f"{self.m.get_name()}: cannot connect {a.get_name()}.{a_out!r} -> {b.get_name()}.{b_in!r}")

    def to(self, a, a_out, prop):
        ok = MEL.connect_material_property(a, a_out, prop)
        if not ok:
            raise RuntimeError(f"{self.m.get_name()}: cannot connect {a.get_name()}.{a_out!r} -> {prop}")

    def slab(self, **pins):
        """Substrate Slab BSDF. pins: python names -> (expr, out). Names map to the slab's input labels."""
        names = {"albedo": "Diffuse Albedo", "f0": "F0", "f90": "F90", "roughness": "Roughness", "normal": "Normal",
                 "sss_mfp": "SSS MFP", "sss_mfp_scale": "SSS MFP Scale", "fuzz_amount": "Fuzz Amount", "fuzz_color": "Fuzz Color",
                 "fuzz_roughness": "Fuzz Roughness", "second_roughness": "Second Roughness", "second_roughness_weight": "Second Roughness Weight",
                 "emissive": "Emissive Color", "anisotropy": "Anisotropy"}
        s = self.e(unreal.MaterialExpressionSubstrateSlabBSDF)
        for k, (src, pin) in pins.items():
            self.link(src, pin, s, names[k])
        return s

    def front(self, substrate_node):
        """Wire a Substrate BSDF/operator into the material's Front Material."""
        self.to(substrate_node, "", unreal.MaterialProperty.MP_FRONT_MATERIAL)

    def finish(self):
        MEL.layout_material_expressions(self.m)
        MEL.recompile_material(self.m)
        EAL.save_loaded_asset(self.m)
        unreal.log(f"MATERIAL built {self.m.get_path_name()}")
        return self.m


def world_pos(g):
    return g.e(unreal.MaterialExpressionWorldPosition)


def local_pos(g):
    return g.e(unreal.MaterialExpressionLocalPosition)


def instance(parent, path, scalars=None, vectors=None):
    pkg, name = path.rsplit("/", 1)
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    mi = AT.create_asset(name, pkg, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    for k, v in (scalars or {}).items():
        MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
    for k, v in (vectors or {}).items():
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*v))
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi)
    return mi
