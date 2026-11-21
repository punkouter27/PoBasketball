using System;
using System.Diagnostics;
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
			"AudioMixer",
			"Niagara",
			"HairStrandsCore",
			"CinematicCamera",
			"DeveloperSettings"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			"PhysicsCore", "LearningAgents", "LearningAgentsTraining", "Learning", "LearningTraining",
			"NNERuntimeBasicCpu"
		});

		PublicIncludePaths.Add(ModuleDirectory);

		// One version stamp (Po Game Standard): UTC yyMMdd of the HEAD commit (the web build uses the same rule), else today (UTC).
		string Stamp = DateTime.UtcNow.ToString("yyMMdd");
		try
		{
			var Git = Process.Start(new ProcessStartInfo("git", "log -1 --format=%ct")
				{ WorkingDirectory = ModuleDirectory, RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true });
			string Out = Git.StandardOutput.ReadToEnd().Trim();
			Git.WaitForExit();
			long Secs;
			if (Git.ExitCode == 0 && long.TryParse(Out, out Secs)) Stamp = DateTimeOffset.FromUnixTimeSeconds(Secs).UtcDateTime.ToString("yyMMdd");
		}
		catch (Exception) {}
		PublicDefinitions.Add("STREETBALL_BUILD_VERSION=\"" + Stamp + "\"");
	}
}
