#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "PresentationEvents.h"
#include "StreetballCrowd.generated.h"

class USkeletalMeshComponent;

UENUM()
enum class ECrowdMood : uint8
{
	Idle,
	Cheer,
	Groan
};

/** Pre-allocated sideline spectator actor (visual only, Chaos off, no collision). */
UCLASS()
class STREETBALLGYM_API AStreetballSpectatorActor : public AActor
{
	GENERATED_BODY()
public:
	AStreetballSpectatorActor();

	UPROPERTY(VisibleAnywhere) TObjectPtr<USkeletalMeshComponent> Mesh;
	FVector BaseLocationUE = FVector::ZeroVector;
	float BaseYawDeg = 0.f;
	float PhaseOffset = 0.f;
	float BounceAmpCm = 18.f;
};

/**
 * Sideline spectator crowd (#15): pre-allocated at BeginPlay inside AStreetballWorld::SetupPresentation,
 * strictly read-only on presentation events (never touches MuJoCo).
 */
class STREETBALLGYM_API FCourtCrowdPlayer
{
public:
	void Initialize(UWorld* World, int32 Seed, int32 Count = 16);
	void OnEvent(EPresentationEvent E, double Now);
	void Tick(double Now, const FVector& FocusUE);
	void SetHidden(bool bHidden);

	int32 NumSpectators() const { return Spectators.Num(); }
	ECrowdMood GetMood() const { return Mood; }
	int32 GetReactionCount() const { return ReactionCount; }

private:
	TArray<TWeakObjectPtr<AStreetballSpectatorActor>> Spectators;
	ECrowdMood Mood = ECrowdMood::Idle;
	double MoodUntil = -1.0;
	int32 ReactionCount = 0;
};
