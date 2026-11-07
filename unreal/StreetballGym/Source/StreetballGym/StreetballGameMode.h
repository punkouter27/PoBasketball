#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "StreetballGameMode.generated.h"

class AStreetballWorld;

/** No pawn, no player input: the showcase is fully autonomous. Ensures one AStreetballWorld exists. */
UCLASS()
class STREETBALLGYM_API AStreetballGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AStreetballGameMode();

protected:
	virtual void BeginPlay() override;

	UPROPERTY() TObjectPtr<AStreetballWorld> World = nullptr;
};
