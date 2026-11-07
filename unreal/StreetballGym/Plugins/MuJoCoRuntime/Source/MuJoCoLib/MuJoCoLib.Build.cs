using System.IO;
using UnrealBuildTool;

// Third-party wrapper for the vendored libmujoco 4.0.0 (ThirdParty/mujoco).
public class MuJoCoLib : ModuleRules
{
	public MuJoCoLib(ReadOnlyTargetRules Target) : base(Target)
	{
		Type = ModuleType.External;

		string ThirdParty = Path.GetFullPath(Path.Combine(ModuleDirectory, "..", "..", "ThirdParty", "mujoco"));
		PublicSystemIncludePaths.Add(Path.Combine(ThirdParty, "include"));

		if (Target.Platform == UnrealTargetPlatform.Win64)
		{
			PublicAdditionalLibraries.Add(Path.Combine(ThirdParty, "lib", "mujoco.lib"));
			PublicDelayLoadDLLs.Add("mujoco.dll");
			RuntimeDependencies.Add("$(BinaryOutputDir)/mujoco.dll", Path.Combine(ThirdParty, "bin", "mujoco.dll"));
			PublicDefinitions.Add("MUJOCO_DLL_DIR=\"" + Path.Combine(ThirdParty, "bin").Replace("\\", "/") + "\"");
		}
	}
}
