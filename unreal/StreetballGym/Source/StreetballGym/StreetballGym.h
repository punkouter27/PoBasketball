#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Stats/Stats.h"

STREETBALLGYM_API DECLARE_LOG_CATEGORY_EXTERN(LogStreetball, Log, All);
DECLARE_STATS_GROUP(TEXT("Streetball"), STATGROUP_Streetball, STATCAT_Advanced);

/** Paths to the sim assets shipped in Content/Project/RL_Policies (copied from sim/assets and shared/ by Phase B). */
namespace Streetball
{
	STREETBALLGYM_API FString SimDir();                 // <Project>/Content/Project/RL_Policies
	STREETBALLGYM_API FString SceneXmlPath();           // .../scene.xml
	STREETBALLGYM_API FString ObsSpecPath();            // .../obs_spec.json
	STREETBALLGYM_API FString HumanoidSpecPath();       // .../humanoid_spec.json
	STREETBALLGYM_API FString RepoSharedDir();          // <repo>/shared (dev only; used by tests)
}
