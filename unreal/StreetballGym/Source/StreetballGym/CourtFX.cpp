#include "CourtFX.h"
#include "StreetballGym.h"
#include "NiagaraComponent.h"
#include "NiagaraSystem.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"

UNiagaraSystem* UCourtFXBank::SystemFor(ECourtFX Fx) const
{
	switch (Fx)
	{
	case ECourtFX::BallDust: return BallDust;
	case ECourtFX::RimSparks: return RimSparks;
	case ECourtFX::BoardDust: return BoardDust;
	case ECourtFX::Swish: return Swish;
	case ECourtFX::FootDust: return FootDust;
	case ECourtFX::Sweat: return Sweat;
	default: return nullptr;
	}
}

bool FCourtFXMapping::FromAudioEvent(const FCourtAudioEvent& E, FCourtFXCue& Out) const
{
	const float S01 = FMath::Clamp(E.Speed / SpeedForFull, 0.f, 1.f);
	Out.PositionUE = E.PositionUE;
	Out.NormalUE = E.NormalUE;
	Out.Surface = E.Surface;
	Out.ImpactSpeed = E.Speed;
	switch (E.Kind)
	{
	case ECourtSound::BallFloor:
		if (E.Speed < DustMinSpeed) return false;
		Out.Fx = ECourtFX::BallDust; Out.Scale = FMath::Lerp(0.5f, 1.4f, S01); return true;
	case ECourtSound::BallRim:
		if (E.Speed < SparkMinSpeed) return false;
		Out.Fx = ECourtFX::RimSparks; Out.Scale = FMath::Lerp(0.6f, 1.3f, S01); return true;
	case ECourtSound::BallBoard:
		Out.Fx = ECourtFX::BoardDust; Out.Scale = FMath::Lerp(0.5f, 1.2f, S01); return true;
	case ECourtSound::NetRattle:
		Out.Fx = ECourtFX::Swish; Out.Scale = 1.f; return true;
	case ECourtSound::ShoeFloor:
		if (E.Speed < FootDustMinSpeed) return false;
		Out.Fx = ECourtFX::FootDust; Out.Scale = FMath::Lerp(0.6f, 1.3f, FMath::Clamp(E.Speed / 4.f, 0.f, 1.f)); return true;
	default:
		return false;
	}
}

void FCourtFXPlayer::Initialize(AActor* Owner, UCourtFXBank* InBank, const FVector RimCentersUE[2], int32 PoolPerFx)
{
	Bank = InBank;
	for (int32 f = 0; f < (int32)ECourtFX::Count; ++f) { Pools[f].Reset(); Next[f] = 0; }
	if (!Owner || !InBank) return;
	Mapping.DustMinSpeed = InBank->DustMinSpeed;
	Mapping.SparkMinSpeed = InBank->SparkMinSpeed;
	Mapping.FootDustMinSpeed = InBank->FootDustMinSpeed;

	auto MakeComp = [Owner](UNiagaraSystem* Sys, const TCHAR* Name, const FVector& At, bool bAuto) -> UNiagaraComponent*
	{
		UNiagaraComponent* C = NewObject<UNiagaraComponent>(Owner, Name);
		C->SetAsset(Sys);
		C->SetAutoActivate(bAuto);
		C->SetAutoDestroy(false);
		C->SetupAttachment(Owner->GetRootComponent());
		C->SetUsingAbsoluteLocation(true);
		C->SetUsingAbsoluteRotation(true);
		C->SetUsingAbsoluteScale(true);
		C->SetWorldLocation(At);
		C->RegisterComponent();
		return C;
	};

	for (int32 f = 0; f < (int32)ECourtFX::Count; ++f)
	{
		UNiagaraSystem* Sys = InBank->SystemFor((ECourtFX)f);
		if (!Sys) continue;
		for (int32 i = 0; i < PoolPerFx; ++i)
		{
			Pools[f].Add(MakeComp(Sys, *FString::Printf(TEXT("CourtFX_%d_%d"), f, i), FVector::ZeroVector, false));
		}
	}
	// ambience: always on, placed once
	if (InBank->Leaves) MakeComp(InBank->Leaves, TEXT("Ambience_Leaves"), FVector(0, 0, 900), true);
	if (InBank->Motes) MakeComp(InBank->Motes, TEXT("Ambience_Motes"), FVector(0, 0, 150), true);
	if (InBank->Pigeons) PigeonComp = MakeComp(InBank->Pigeons, TEXT("Ambience_Pigeons"), PerchUE, false);

	// nets: hang from each rim centre
	if (InBank->NetMesh)
	{
		for (int32 r = 0; r < 2; ++r)
		{
			UStaticMeshComponent* Net = NewObject<UStaticMeshComponent>(Owner, *FString::Printf(TEXT("Net_%d"), r));
			Net->SetStaticMesh(InBank->NetMesh);
			Net->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Net->SetSimulatePhysics(false);
			Net->SetupAttachment(Owner->GetRootComponent());
			Net->SetUsingAbsoluteLocation(true);
			Net->SetUsingAbsoluteRotation(true);
			Net->SetWorldLocation(RimCentersUE[r]);
			Net->RegisterComponent();
			if (InBank->NetMaterial)
			{
				UMaterialInstanceDynamic* MID = UMaterialInstanceDynamic::Create(InBank->NetMaterial, Net);
				MID->SetScalarParameterValue(TEXT("SwishTime"), -100.f);
				MID->SetScalarParameterValue(TEXT("HitTime"), -100.f);
				Net->SetMaterial(0, MID);
				NetMID[r] = MID;
			}
		}
	}
}

void FCourtFXPlayer::Play(const FCourtFXCue& Cue)
{
	++PlayedCount;
	TArray<TWeakObjectPtr<UNiagaraComponent>>& Pool = Pools[(int32)Cue.Fx];
	if (Pool.Num() == 0) return;
	int32& N = Next[(int32)Cue.Fx];
	UNiagaraComponent* C = Pool[N].Get();
	N = (N + 1) % Pool.Num();
	if (!C) return;
	C->SetWorldLocation(Cue.PositionUE);
	const FVector NormalDir = Cue.NormalUE.GetSafeNormal();
	C->SetWorldRotation(NormalDir.IsNearlyZero() ? FQuat::Identity : FRotationMatrix::MakeFromZ(NormalDir).ToQuat());
	C->SetWorldScale3D(FVector(Cue.Scale));
	C->SetFloatParameter(TEXT("User.ImpactSpeed"), Cue.ImpactSpeed);
	C->SetFloatParameter(TEXT("User.SurfaceHardness"), UCourtAudioBank::SurfaceHardness(Cue.Surface));
	C->Activate(true);
}

void FCourtFXPlayer::KickNet(int32 RimIndex, bool bSwish, double Now, float Intensity)
{
	if (RimIndex < 0 || RimIndex > 1) return;
	++NetKicks;
	if (UMaterialInstanceDynamic* MID = NetMID[RimIndex].Get())
	{
		MID->SetScalarParameterValue(bSwish ? TEXT("SwishTime") : TEXT("HitTime"), (float)Now);
		MID->SetScalarParameterValue(bSwish ? TEXT("SwishIntensity") : TEXT("HitIntensity"), FMath::Clamp(Intensity, 0.2f, 2.f));
	}
}

void FCourtFXPlayer::NotifyBallLanding(const FVector& BallUE, double Now)
{
	UNiagaraComponent* C = PigeonComp.Get();
	if (!C || Now - LastPigeonT < PigeonCooldown) return;
	if (FVector2D(BallUE.X - PerchUE.X, BallUE.Y - PerchUE.Y).Size() > PerchRadius) return;
	LastPigeonT = Now;
	C->Activate(true);
}
