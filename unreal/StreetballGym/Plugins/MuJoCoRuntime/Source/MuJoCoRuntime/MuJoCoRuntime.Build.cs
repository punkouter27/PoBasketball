using UnrealBuildTool;

public class MuJoCoRuntime : ModuleRules
{
	public MuJoCoRuntime(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"Projects",
			"MuJoCoLib"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
