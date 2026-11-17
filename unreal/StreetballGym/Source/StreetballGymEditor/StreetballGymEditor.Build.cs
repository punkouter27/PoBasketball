using UnrealBuildTool;

/** Editor-only helpers exposed to the headless Python build scripts (Scripts/make_*.py). Never loaded in -game. */
public class StreetballGymEditor : ModuleRules
{
	public StreetballGymEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PrivateDependencyModuleNames.AddRange(new string[] {
			"UnrealEd", "Niagara", "NiagaraCore",
			"ClothingSystemRuntimeCommon", "ClothingSystemRuntimeInterface", "ClothingSystemEditorInterface",
			"ChaosCloth", "RenderCore", "RHI"
		});
	}
}
