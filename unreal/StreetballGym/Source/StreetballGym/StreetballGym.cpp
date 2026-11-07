#include "StreetballGym.h"
#include "Misc/Paths.h"

DEFINE_LOG_CATEGORY(LogStreetball);

IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, StreetballGym, "StreetballGym");

namespace Streetball
{
	FString SimDir() { return FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Sim")); }
	FString SceneXmlPath() { return FPaths::Combine(SimDir(), TEXT("scene.xml")); }
	FString ObsSpecPath() { return FPaths::Combine(SimDir(), TEXT("obs_spec.json")); }
	FString HumanoidSpecPath() { return FPaths::Combine(SimDir(), TEXT("humanoid_spec.json")); }
	FString RepoSharedDir() { return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("../../shared"))); }
}
