#include "StreetballCrowd.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "UObject/ConstructorHelpers.h"

AStreetballSpectatorActor::AStreetballSpectatorActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Mesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Mesh"));
	SetRootComponent(Mesh);
	Mesh->SetSimulatePhysics(false);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetEnableGravity(false);
	// Mesh faces +Y in local space; rotate -90 deg so actor +X is facing direction.
	Mesh->SetRelativeRotation(FRotator(0.f, -90.f, 0.f));
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> Manny(TEXT("/Game/Project/Agents/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple"));
	if (Manny.Succeeded()) Mesh->SetSkeletalMeshAsset(Manny.Object);
}

void FCourtCrowdPlayer::Initialize(UWorld* World, int32 Seed, int32 Count)
{
	Spectators.Reset();
	Mood = ECrowdMood::Idle;
	MoodUntil = -1.0;
	ReactionCount = 0;
	if (!World || Count <= 0) return;

	USkeletalMesh* Manny = LoadObject<USkeletalMesh>(nullptr, TEXT("/Game/Project/Agents/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple"), nullptr, LOAD_NoWarn | LOAD_Quiet);
	USkeletalMesh* Quinn = LoadObject<USkeletalMesh>(nullptr, TEXT("/Game/Project/Agents/Mannequins/Meshes/SKM_Quinn_Simple.SKM_Quinn_Simple"), nullptr, LOAD_NoWarn | LOAD_Quiet);
	FRandomStream Rng(Seed * 4999 + 31);

	FActorSpawnParameters SP;
	SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	// Place onlookers along the north sideline sidewalk (sim y = +10.6 m -> UE y = -1060 cm, outside the 9.5 m fence)
	// and behind the east/west baselines (sim x = +-16.9 m -> UE x = +-1690 cm), directly visible in Broadcast shots.
	const int32 NorthCount = FMath::Max(1, (Count * 3) / 4);
	for (int32 i = 0; i < Count; ++i)
	{
		FVector PosUE;
		float YawDeg = 90.f;
		if (i < NorthCount)
		{
			const float T = NorthCount > 1 ? static_cast<float>(i) / (NorthCount - 1) : 0.5f;
			const float Xm = FMath::Lerp(-12.5f, 12.5f, T) + Rng.FRandRange(-0.35f, 0.35f);
			const float Ym = 10.55f + Rng.FRandRange(-0.25f, 0.35f);
			PosUE = FVector(Xm * 100.f, -Ym * 100.f, 10.f); // 10 cm sidewalk height
			YawDeg = 90.f + Rng.FRandRange(-12.f, 12.f);    // face +Y (toward court centre)
		}
		else
		{
			const int32 SideIdx = i - NorthCount;
			const float SignX = (SideIdx % 2 == 0) ? 1.f : -1.f;
			const float Ym = (SideIdx / 2 == 0 ? -3.0f : 3.0f) + Rng.FRandRange(-0.6f, 0.6f);
			PosUE = FVector(SignX * 1690.f, -Ym * 100.f, 10.f);
			YawDeg = SignX > 0.f ? 180.f : 0.f;
		}

		AStreetballSpectatorActor* S = World->SpawnActor<AStreetballSpectatorActor>(AStreetballSpectatorActor::StaticClass(), FTransform(FRotator(0.f, YawDeg, 0.f), PosUE), SP);
		if (!S) continue;
		if ((i % 2 == 1) && Quinn) S->Mesh->SetSkeletalMeshAsset(Quinn);
		else if (Manny) S->Mesh->SetSkeletalMeshAsset(Manny);
		const float Scale = Rng.FRandRange(0.92f, 1.06f);
		S->SetActorScale3D(FVector(Scale));
		S->BaseLocationUE = PosUE;
		S->BaseYawDeg = YawDeg;
		S->PhaseOffset = Rng.FRandRange(0.f, 2.f * PI);
		S->BounceAmpCm = Rng.FRandRange(14.f, 26.f);
		Spectators.Add(S);
	}
}

void FCourtCrowdPlayer::OnEvent(EPresentationEvent E, double Now)
{
	switch (E)
	{
	case EPresentationEvent::Make:
	case EPresentationEvent::Swish:
	case EPresentationEvent::ScrambleSave:
	case EPresentationEvent::TierUp:
		Mood = ECrowdMood::Cheer;
		MoodUntil = Now + 2.4;
		++ReactionCount;
		break;
	case EPresentationEvent::Miss:
	case EPresentationEvent::RimOut:
	case EPresentationEvent::Fall:
		Mood = ECrowdMood::Groan;
		MoodUntil = Now + 1.8;
		++ReactionCount;
		break;
	default:
		break;
	}
}

void FCourtCrowdPlayer::Tick(double Now, const FVector& FocusUE)
{
	if (Mood != ECrowdMood::Idle && Now >= MoodUntil)
	{
		Mood = ECrowdMood::Idle;
	}
	for (const TWeakObjectPtr<AStreetballSpectatorActor>& Ptr : Spectators)
	{
		AStreetballSpectatorActor* S = Ptr.Get();
		if (!S) continue;
		const float Phase = static_cast<float>(Now) + S->PhaseOffset;
		const float ToFocusYaw = static_cast<float>(FRotationMatrix::MakeFromX(FocusUE - S->BaseLocationUE).Rotator().Yaw);
		// Blend gently between base facing and ball/athlete tracking so onlookers stay oriented toward the court.
		const float DeltaYaw = FMath::FindDeltaAngleDegrees(S->BaseYawDeg, ToFocusYaw);
		const float TrackYaw = S->BaseYawDeg + FMath::Clamp(DeltaYaw, -35.f, 35.f);

		float ZOff = 0.f;
		float Pitch = 0.f;
		float YawJitter = 0.f;
		if (Mood == ECrowdMood::Cheer)
		{
			const float Hop = FMath::Abs(FMath::Sin(Phase * 7.5f));
			ZOff = Hop * S->BounceAmpCm;
			Pitch = -5.f * Hop;
			YawJitter = 6.f * FMath::Sin(Phase * 9.0f);
		}
		else if (Mood == ECrowdMood::Groan)
		{
			ZOff = -6.f * (0.5f + 0.5f * FMath::Sin(Phase * 3.0f));
			Pitch = 8.f;
			YawJitter = 12.f * FMath::Sin(Phase * 10.0f);
		}
		else
		{
			ZOff = 1.8f * FMath::Sin(Phase * 2.2f);
			Pitch = 1.5f * FMath::Sin(Phase * 1.4f);
		}
		S->SetActorLocationAndRotation(S->BaseLocationUE + FVector(0.f, 0.f, ZOff), FRotator(Pitch, TrackYaw + YawJitter, 0.f));
	}
}

void FCourtCrowdPlayer::SetHidden(bool bHidden)
{
	for (const TWeakObjectPtr<AStreetballSpectatorActor>& Ptr : Spectators)
	{
		if (AStreetballSpectatorActor* S = Ptr.Get()) S->SetActorHiddenInGame(bHidden);
	}
}
