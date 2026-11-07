#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "CourtAudio.generated.h"

class UMuJoCoSim;
class USoundBase;
class UAudioComponent;
class AActor;

UENUM(BlueprintType)
enum class ECourtSound : uint8
{
	BallFloor,
	BallPalm,
	ShoeFloor,
	BallRim,
	BallBoard,
	NetRattle,
	Count UMETA(Hidden)
};

/** PRD 3.2 sound mapping. Placeholder waves come from Scripts/make_audio_assets.py; swap in real samples here. */
UCLASS(BlueprintType)
class STREETBALLGYM_API UCourtAudioBank : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Sounds") TObjectPtr<USoundBase> BallFloor;
	UPROPERTY(EditAnywhere, Category = "Sounds") TObjectPtr<USoundBase> BallPalm;
	UPROPERTY(EditAnywhere, Category = "Sounds") TObjectPtr<USoundBase> ShoeFloor;
	UPROPERTY(EditAnywhere, Category = "Sounds") TObjectPtr<USoundBase> BallRim;
	UPROPERTY(EditAnywhere, Category = "Sounds") TObjectPtr<USoundBase> BallBoard;
	UPROPERTY(EditAnywhere, Category = "Sounds") TObjectPtr<USoundBase> NetRattle;
	/** Impact speed (m/s) that maps to full volume. */
	UPROPERTY(EditAnywhere, Category = "Mapping") float SpeedForFullVolume = 8.f;
	UPROPERTY(EditAnywhere, Category = "Mapping") float MinVolume = 0.15f;
	/** Pitch = 1 + PitchRange * (speed/SpeedForFullVolume - 0.5), clamped. */
	UPROPERTY(EditAnywhere, Category = "Mapping") float PitchRange = 0.4f;

	USoundBase* SoundFor(ECourtSound S) const;
};

/** One fired event (also kept in a ring buffer for tests and debugging). */
struct STREETBALLGYM_API FCourtAudioEvent
{
	ECourtSound Kind = ECourtSound::BallFloor;
	double Time = 0.0;              // sim time
	FVector PositionUE = FVector::ZeroVector;
	float Speed = 0.f;              // impact speed m/s
	float Volume = 1.f;
	float Pitch = 1.f;
	FString Pair;                   // "ball|floor" etc.
};

/**
 * Per-physics-step contact sampler: rising edge per geom pair -> debounced event with impact
 * speed, mapped to volume/pitch. Engine-free except for the playback hook, so tests can feed a
 * scripted sim.
 */
struct STREETBALLGYM_API FContactAudioProcessor
{
	bool Initialize(UMuJoCoSim* Sim);
	/** Call after every mj_step. Appends new events to OutEvents (does not clear it). */
	void Process(UMuJoCoSim* Sim, TArray<FCourtAudioEvent>& OutEvents);
	/** External event (e.g. a score) at a sim-space position. */
	FCourtAudioEvent MakeEvent(ECourtSound Kind, double Time, const FVector3d& PosSim, float Speed, const FString& Pair) const;

	double DebounceS = 0.06;
	double ShoeLateralMin = 0.5;     // m/s
	float SpeedForFullVolume = 8.f, MinVolume = 0.15f, PitchRange = 0.4f;

private:
	int32 Floor = -1, Ball = -1, Foot[2] = {-1, -1}, Palm[2] = {-1, -1}, FootBody[2] = {-1, -1};
	int32 BallQ = -1, BallV = -1;
	TArray<bool> RimMask, BoardMask;
	TSet<uint64> ActivePairs;          // pairs in contact last step
	TMap<uint64, double> LastFire;     // debounce per pair
	static uint64 Key(int32 A, int32 B) { if (A > B) Swap(A, B); return ((uint64)(uint32)A << 32) | (uint32)B; }
};

/** Owns a fixed pool of audio components (no per-event allocation) and plays events through the bank. */
class STREETBALLGYM_API FCourtAudioPlayer
{
public:
	void Initialize(AActor* Owner, UCourtAudioBank* InBank, int32 PoolSize = 8);
	void Play(const FCourtAudioEvent& E);
	bool HasBank() const { return Bank != nullptr; }
	int32 PlayedCount = 0;
private:
	TWeakObjectPtr<UCourtAudioBank> Bank;
	TArray<TWeakObjectPtr<UAudioComponent>> Pool;
	int32 Next = 0;
};
