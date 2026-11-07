#include "StreetballGameMode.h"
#include "StreetballWorld.h"
#include "StreetballGym.h"
#include "EngineUtils.h"
#include "GameFramework/SpectatorPawn.h"

AStreetballGameMode::AStreetballGameMode()
{
	DefaultPawnClass = ASpectatorPawn::StaticClass();   // a camera only; no gameplay input is wired
	bStartPlayersAsSpectators = true;
}

void AStreetballGameMode::BeginPlay()
{
	Super::BeginPlay();
	for (TActorIterator<AStreetballWorld> It(GetWorld()); It; ++It)
	{
		World = *It;
		break;
	}
	if (!World)
	{
		// Only allowed spawn outside of AStreetballWorld::BeginPlay: the world actor itself,
		// and only when the level author did not place one.
		World = GetWorld()->SpawnActor<AStreetballWorld>(AStreetballWorld::StaticClass(), FTransform::Identity);
		UE_LOG(LogStreetball, Log, TEXT("Spawned AStreetballWorld (none placed in level)"));
	}
}
