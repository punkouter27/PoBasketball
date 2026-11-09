#include "CourtAudio.h"
#include "MuJoCoSim.h"
#include "StreetballGym.h"
#include "Components/AudioComponent.h"
#include "Sound/SoundBase.h"
#include "GameFramework/Actor.h"

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
		if (HasBall && HasFloor) { Kind = ECourtSound::BallFloor; Pair = TEXT("ball|floor"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasBall && (Other == Palm[0] || Other == Palm[1])) { Kind = ECourtSound::BallPalm; Pair = TEXT("ball|palm"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasBall && RimMask.IsValidIndex(Other) && RimMask[Other]) { Kind = ECourtSound::BallRim; Pair = TEXT("ball|rim"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasBall && BoardMask.IsValidIndex(Other) && BoardMask[Other]) { Kind = ECourtSound::BallBoard; Pair = TEXT("ball|board"); Speed = (float)BallVel.Length(); bValid = true; }
		else if (HasFloor && (Other == Foot[0] || Other == Foot[1]))
		{
			const int32 i = (Other == Foot[0]) ? 0 : 1;
			const FVector3d FV = Sim->GetBodyLinearVelocitySim(FootBody[i]);
			const double Lateral = FVector2d(FV.X, FV.Y).Length();
			if (Lateral > ShoeLateralMin) { Kind = ECourtSound::ShoeFloor; Pair = i == 0 ? TEXT("foot_l|floor") : TEXT("foot_r|floor"); Speed = (float)Lateral; bValid = true; }
			else { Now.Add(Key(g0, g1)); continue; }   // quiet touchdown: still counts as active so no late trigger
		}
		if (!bValid) continue;
		const uint64 K = Key(g0, g1);
		Now.Add(K);
		if (ActivePairs.Contains(K)) continue;                        // not a rising edge
		const double* Last = LastFire.Find(K);
		if (Last && (T - *Last) < DebounceS) continue;                // debounced
		LastFire.Add(K, T);
		Out.Add(MakeEvent(Kind, T, FVector3d(C.pos[0], C.pos[1], C.pos[2]), Speed, Pair));
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
		AC->SetupAttachment(Owner->GetRootComponent());
		AC->RegisterComponent();
		Pool.Add(AC);
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
	AC->SetPitchMultiplier(E.Pitch);
	AC->Play();
}
