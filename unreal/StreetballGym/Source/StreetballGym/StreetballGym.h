#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

STREETBALLGYM_API DECLARE_LOG_CATEGORY_EXTERN(LogStreetball, Log, All);

/** Paths to the sim assets shipped in Content/Sim (copied from sim/assets and shared/ by Phase B). */
namespace Streetball
{
	STREETBALLGYM_API FString SimDir();                 // <Project>/Content/Sim
	STREETBALLGYM_API FString SceneXmlPath();           // .../scene.xml
	STREETBALLGYM_API FString ObsSpecPath();            // .../obs_spec.json
	STREETBALLGYM_API FString HumanoidSpecPath();       // .../humanoid_spec.json
	STREETBALLGYM_API FString RepoSharedDir();          // <repo>/shared (dev only; used by tests)
}
