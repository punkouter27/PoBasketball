#include "CourtAudio.h"
#include "MuJoCoSim.h"
#include "StreetballGym.h"
#include "Components/AudioComponent.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundBase.h"
#include "GameFramework/Actor.h"

float UCourtAudioBank::SurfaceHardness(EStreetballSurface S)
{
	switch (S)
	{
	case EStreetballSurface::SteelRim:  return 1.0f;
	case EStreetballSurface::Asphalt:   return 0.85f;
	case EStreetballSurface::WoodBoard: return 0.60f;
	case EStreetballSurface::Leather:   return 0.25f;
	default:                            return 0.50f;
	}
}

USoundBase* UCourtAudioBank::SoundFor(ECourtSound S) const
{
	switch (S)
	{
	case ECourtSound::BallFloor: return BallFloor;
	case ECourtSound::BallPalm: return BallPalm;
	case ECourtSound::ShoeFloor: return ShoeFloor;
	case ECourtSound::BallRim: return BallRim;
	case ECourtSound::BallBoard: return BallBoard;
	case ECourtSound::NetRattle: return NetRattle;
	case ECourtSound::CrowdCheer: return CrowdCheer;
	case ECourtSound::CrowdGroan: return CrowdGroan;
	case ECourtSound::Grunt: return Grunt;
	default: return nullptr;
	}
}

// ---------------------------------------------------------------------------- processor
bool FContactAudioProcessor::Initialize(UMuJoCoSim* Sim)
{
	if (!Sim || !Sim->IsLoaded()) return false;
	const mjModel* M = Sim->GetModel();
	Floor = Sim->GeomId(TEXT("floor"));
	Ball = Sim->GeomId(TEXT("ball"));
	Foot[0] = Sim->GeomId(TEXT("foot_l")); Foot[1] = Sim->GeomId(TEXT("foot_r"));
	Toe[0] = Sim->GeomId(TEXT("toe_l")); Toe[1] = Sim->GeomId(TEXT("toe_r"));
	Palm[0] = Sim->GeomId(TEXT("palm_l")); Palm[1] = Sim->GeomId(TEXT("palm_r"));
	FootBody[0] = Sim->BodyId(TEXT("foot_l")); FootBody[1] = Sim->BodyId(TEXT("foot_r"));
	const int32 BallJ = Sim->JointId(TEXT("ball"));
	BallQ = M->jnt_qposadr[BallJ]; BallV = M->jnt_dofadr[BallJ];
	RimMask.SetNumZeroed(M->ngeom); BoardMask.SetNumZeroed(M->ngeom);
	for (int32 g = 0; g < M->ngeom; ++g)
	{
		const FString N = Sim->GeomName(g);
		RimMask[g] = N.StartsWith(TEXT("rim_")) && !N.StartsWith(TEXT("rim_bracket"));
		BoardMask[g] = N.StartsWith(TEXT("board_"));
	}
	ActivePairs.Reset(); ScratchPairs.Reset(); LastFire.Reset();
	ActivePairs.Reserve(64); ScratchPairs.Reserve(64); LastFire.Reserve(64);
	return Floor >= 0 && Ball >= 0;
}

FCourtAudioEvent FContactAudioProcessor::MakeEvent(ECourtSound Kind, double Time, const FVector3d& PosSim, float Speed, const TCHAR* Pair) const
{
	FCourtAudioEvent E;
	E.Kind = Kind; E.Time = Time; E.Speed = Speed; E.Pair = Pair;
	E.PositionUE = FVector(PosSim.X * 100.0, -PosSim.Y * 100.0, PosSim.Z * 100.0);
	const float S = FMath::Clamp(Speed / SpeedForFullVolume, 0.f, 1.f);
	E.Volume = FMath::Lerp(MinVolume, 1.f, S);
	E.Pitch = FMath::Clamp(1.f + PitchRange * (S - 0.5f), 0.5f, 2.f);
	return E;
}

void FContactAudioProcessor::Process(UMuJoCoSim* Sim, TArray<FCourtAudioEvent>& Out)
{
	const mjModel* M = Sim->GetModel();
	const mjData* D = Sim->GetData();
	const double T = D->time;
	TSet<uint64>& Now = ScratchPairs;
	Now.Reset();                                   // keeps its allocation
	const FVector3d BallVel(D->qvel[BallV], D->qvel[BallV + 1], D->qvel[BallV + 2]);

	for (int32 c = 0; c < D->ncon; ++c)
	{
		const mjContact& C = D->contact[c];
		const int32 g0 = C.geom[0], g1 = C.geom[1];
		ECourtSound Kind = ECourtSound::BallFloor; const TCHAR* Pair = TEXT(""); float Speed = 0.f; bool bValid = false;
		const bool HasBall = (g0 == Ball || g1 == Ball);
		const bool HasFloor = (g0 == Floor || g1 == Floor);
		const int32 Other = HasBall ? (g0 == Ball ? g1 : g0) : (g0 == Floor ? g1 : g0);
		EStreetballSurface Surface = EStreetballSurface::Unknown;
		if (HasBall && HasFloor) { Kind = ECourtSound::BallFloor; Surface = EStreetballSurface::Asphalt; Pair = TEXT("ball|floor"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasBall && (Other == Palm[0] || Other == Palm[1])) { Kind = ECourtSound::BallPalm; Surface = EStreetballSurface::Leather; Pair = TEXT("ball|palm"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasBall && RimMask.IsValidIndex(Other) && RimMask[Other]) { Kind = ECourtSound::BallRim; Surface = EStreetballSurface::SteelRim; Pair = TEXT("ball|rim"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasBall && BoardMask.IsValidIndex(Other) && BoardMask[Other]) { Kind = ECourtSound::BallBoard; Surface = EStreetballSurface::WoodBoard; Pair = TEXT("ball|board"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasFloor && (Other == Foot[0] || Other == Foot[1] || (Toe[0] >= 0 && Other == Toe[0]) || (Toe[1] >= 0 && Other == Toe[1])))
		{
			const int32 i = (Other == Foot[0] || Other == Toe[0]) ? 0 : 1;
			const FVector3d FV = Sim->GetBodyLinearVelocitySim(FootBody[i]);
			const double Lateral = FVector2d(FV.X, FV.Y).Length();
			if (Lateral > ShoeLateralMin) { Kind = ECourtSound::ShoeFloor; Surface = EStreetballSurface::Asphalt; Pair = i == 0 ? TEXT("foot_l|floor") : TEXT("foot_r|floor"); Speed = (float)Lateral; bValid = true; }
			else { Now.Add(Key(g0, g1)); continue; }   // quiet touchdown: still counts as active so no late trigger
		}
		if (!bValid) continue;
		const uint64 K = Key(g0, g1);
		Now.Add(K);
		if (ActivePairs.Contains(K)) continue;                        // not a rising edge
		const double* Last = LastFire.Find(K);
		if (Last && (T - *Last) < DebounceS) continue;                // debounced
		LastFire.Add(K, T);
		FCourtAudioEvent Ev = MakeEvent(Kind, T, FVector3d(C.pos[0], C.pos[1], C.pos[2]), Speed, Pair);
		Ev.Surface = Surface;
		// MuJoCo contact frame[0..2] is the contact normal (sim Z-up RH -> UE Z-up LH).
		FVector N(C.frame[0], -C.frame[1], C.frame[2]);
		if (N.Normalize()) Ev.NormalUE = N;
		Out.Add(Ev);
	}
	Swap(ActivePairs, ScratchPairs);
}

// ---------------------------------------------------------------------------- player
void FCourtAudioPlayer::Initialize(AActor* Owner, UCourtAudioBank* InBank, int32 PoolSize)
{
	Bank = InBank;
	Pool.Reset();
	if (!Owner) return;
	for (int32 i = 0; i < PoolSize; ++i)
	{
		UAudioComponent* AC = NewObject<UAudioComponent>(Owner, *FString::Printf(TEXT("CourtAudio%d"), i));
		AC->bAutoActivate = false;
		AC->bAllowSpatialization = true;
		if (InBank && InBank->SpatialAttenuation)
		{
			AC->AttenuationSettings = InBank->SpatialAttenuation;
		}
		else
		{
			AC->bOverrideAttenuation = true;
			AC->AttenuationOverrides.bSpatialize = true;
			AC->AttenuationOverrides.bAttenuate = true;
			AC->AttenuationOverrides.FalloffDistance = 2400.f;
			AC->AttenuationOverrides.bEnableListenerFocus = false;
		}
		AC->SetupAttachment(Owner->GetRootComponent());
		AC->RegisterComponent();
		Pool.Add(AC);
	}
	if (InBank && InBank->ShoeFloor)
	{
		UAudioComponent* SQ = NewObject<UAudioComponent>(Owner, TEXT("CourtAudioShoeSqueak"));
		SQ->bAutoActivate = false;
		SQ->bAllowSpatialization = true;
		SQ->bOverrideAttenuation = true;
		SQ->AttenuationOverrides.bSpatialize = true;
		SQ->AttenuationOverrides.bAttenuate = true;
		SQ->AttenuationOverrides.FalloffDistance = 1800.f;
		SQ->SetSound(InBank->ShoeFloor);
		SQ->SetupAttachment(Owner->GetRootComponent());
		SQ->RegisterComponent();
		ShoeSqueakComp = SQ;
	}
}

void FCourtAudioPlayer::Play(const FCourtAudioEvent& E)
{
	++PlayedCount;
	if (!Bank.IsValid() || Pool.Num() == 0) return;
	USoundBase* Snd = Bank->SoundFor(E.Kind);
	if (!Snd) return;
	UAudioComponent* AC = Pool[Next].Get();
	Next = (Next + 1) % Pool.Num();
	if (!AC) return;
	AC->SetWorldLocation(E.PositionUE);
	AC->SetSound(Snd);
	AC->SetVolumeMultiplier(E.Volume);
	// Scale pitch smoothly with sim TimeScale so slow-mo replays sound natural.
	const float ScaledPitch = FMath::Clamp(E.Pitch * FMath::Lerp(1.f, TimeScale, 0.5f), 0.5f, 2.f);
	AC->SetPitchMultiplier(ScaledPitch);
	// MetaSound inputs; ignored by plain waves.
	AC->SetFloatParameter(TEXT("Impact"), FMath::Clamp(E.Speed / FMath::Max(Bank->SpeedForFullVolume, 0.1f), 0.f, 1.f));
	AC->SetFloatParameter(TEXT("SurfaceHardness"), UCourtAudioBank::SurfaceHardness(E.Surface));
	AC->Play();
	if (E.Kind == ECourtSound::CrowdCheer || E.Kind == ECourtSound::CrowdGroan || E.Kind == ECourtSound::Grunt)
	{
		NotifyVoiceOrCrowd(0.9f);
	}
}

void FCourtAudioPlayer::NotifyVoiceOrCrowd(float DurationS)
{
	DuckTimer = FMath::Max(DuckTimer, DurationS);
}

void FCourtAudioPlayer::Tick(float DeltaSeconds)
{
	if (DuckTimer > 0.f) DuckTimer = FMath::Max(0.f, DuckTimer - DeltaSeconds);
	const float TargetDuck = (DuckTimer > 0.f && Bank.IsValid()) ? Bank->AmbienceDuckMultiplier : 1.f;
	CurrentDuck = FMath::FInterpTo(CurrentDuck, TargetDuck, DeltaSeconds, DuckTimer > 0.f ? 14.f : 4.f);
	if (UAudioComponent* AC = AmbienceComp.Get())
	{
		if (Bank.IsValid()) AC->SetVolumeMultiplier(Bank->AmbienceVolume * CurrentDuck);
	}
}

void FCourtAudioPlayer::UpdateShoeSlip(float LateralSpeed, const FVector& PosUE)
{
	UAudioComponent* SQ = ShoeSqueakComp.Get();
	if (!SQ || !Bank.IsValid()) return;
	if (LateralSpeed < 0.75f) return;
	if (!SQ->IsPlaying())
	{
		SQ->SetWorldLocation(PosUE);
		const float Norm = FMath::Clamp((LateralSpeed - 0.75f) / 4.f, 0.f, 1.f);
		SQ->SetVolumeMultiplier(FMath::Lerp(0.08f, 0.45f, Norm));
		SQ->SetPitchMultiplier(FMath::Clamp(0.9f + 0.5f * Norm, 0.7f, 1.6f));
		SQ->SetFloatParameter(TEXT("Impact"), Norm);
		SQ->Play();
	}
}

void FCourtAudioPlayer::StartAmbience(AActor* Owner)
{
	if (!Owner || !Bank.IsValid() || !Bank->Ambience) return;
	UAudioComponent* AC = NewObject<UAudioComponent>(Owner, TEXT("CourtAmbience"));
	AC->bAutoActivate = false;
	AC->bAllowSpatialization = false;
	AC->bIsUISound = false;
	AC->SetupAttachment(Owner->GetRootComponent());
	AC->RegisterComponent();
	AC->SetSound(Bank->Ambience);
	AC->SetVolumeMultiplier(Bank->AmbienceVolume);
	AC->Play();
	AmbienceComp = AC;
}

bool FCourtAudioPlayer::IsAmbiencePlaying() const
{
	const UAudioComponent* AC = AmbienceComp.Get();
	return AC && AC->IsPlaying();
}
