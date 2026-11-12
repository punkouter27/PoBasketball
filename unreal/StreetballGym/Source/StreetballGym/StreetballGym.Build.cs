using UnrealBuildTool;

public class StreetballGym : ModuleRules
{
	public StreetballGym(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"Json",
			"JsonUtilities",
			"NNE",
			"MuJoCoRuntime",
			"UMG",
			"Slate",
			"SlateCore",
			"AudioMixer"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			"PhysicsCore", "LearningAgents", "LearningAgentsTraining", "Learning", "LearningTraining",
			"NNERuntimeBasicCpu"
		});

		PublicIncludePaths.Add(ModuleDirectory);
	}
}
