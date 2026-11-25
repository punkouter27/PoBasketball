#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "PresentationEvents.h"
#include "GrandmaVoice.generated.h"

class USoundBase;
class UAudioComponent;
class USkeletalMeshComponent;

/** One baked line (tools/voice_bake -> Scripts/import_voice_bank.py). Frames are flattened [frame][morph]. */
USTRUCT(BlueprintType)
struct STREETBALLGYM_API FGrandmaVoiceLine
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") FName Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") FName Event;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") FString Text;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") FName Mood;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") TObjectPtr<USoundBase> Sound;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") float Duration = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") int32 NumFrames = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") TArray<float> Frames;
};

/** Offline-baked trash talk: audio + per-frame morph weights (Audio2Face-compatible track layout). */
UCLASS(BlueprintType)
class STREETBALLGYM_API UGrandmaVoiceBank : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") float Fps = 30.f;
	/** Morph target names, in the column order of FGrandmaVoiceLine::Frames. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") TArray<FName> Morphs;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") TArray<FGrandmaVoiceLine> Lines;
	/** Seconds between two lines (any event). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") float MinGapS = 3.5f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Voice") float VolumeMultiplier = 1.2f;
};

/**
 * Picks and plays lines for presentation events, then drives the face: baked lip-sync curves while a line plays,
 * plus blinks and a decaying mood layer. Writes only morph targets on the visual mesh.
 */
class STREETBALLGYM_API FGrandmaVoicePlayer
{
public:
	void Initialize(AActor* Owner, USkeletalMeshComponent* InFace, UGrandmaVoiceBank* InBank, int32 Seed);
	/** Returns the line started, or nullptr (no lines for the event, cooldown, or nothing loaded). */
	const FGrandmaVoiceLine* OnEvent(EPresentationEvent E, double GameTime);
	/** Every frame: sample the active line and write morph targets. */
	void Tick(double GameTime, float DeltaSeconds);
	/** Continuous physical exertion [0..1] from sim actuator power/torque; drives idle breathing & squint/grimace. */
	void SetExertion(float InExertion01) { Exertion01 = FMath::Clamp(InExertion01, 0.f, 1.f); }
	float GetExertion() const { return Exertion01; }
	/** Dribble Lab face mood [0..1] (2026-11-24): CC morphs while no line or voice mood is playing; replaces the exertion grimace while > 0.05. */
	void SetBaseMood(float InSmile01, float InFrown01) { BaseSmile = FMath::Clamp(InSmile01, 0.f, 1.f); BaseFrown = FMath::Clamp(InFrown01, 0.f, 1.f); }
	float GetBaseSmile() const { return BaseSmile; }
	float GetBaseFrown() const { return BaseFrown; }

	bool HasBank() const { return Bank.IsValid() && Bank->Lines.Num() > 0; }
	const FString& GetSubtitle() const { return Subtitle; }
	double GetSubtitleUntil() const { return SubtitleUntil; }
	int32 GetLinesPlayed() const { return LinesPlayed; }
	/** Pure selection (tests): index into Bank->Lines for an event key, avoiding the last pick. INDEX_NONE if none. */
	static int32 PickLine(const UGrandmaVoiceBank& InBank, FName EventKey, FRandomStream& Rng, int32 AvoidIndex);
	/** Pure sampling (tests): linear interpolation of one morph column at time T. */
	static float SampleMorph(const UGrandmaVoiceBank& InBank, const FGrandmaVoiceLine& Line, int32 MorphIndex, float T);

private:
	void ApplyMood(FName Mood, float Strength);

	TWeakObjectPtr<UGrandmaVoiceBank> Bank;
	TWeakObjectPtr<USkeletalMeshComponent> Face;
	TWeakObjectPtr<UAudioComponent> Audio;
	FRandomStream Rng;
	int32 Active = INDEX_NONE;
	int32 LastPicked = INDEX_NONE;
	double StartT = -1.0, LastLineEndT = -100.0;
	double NextBlinkT = 2.0, BlinkT = -1.0;
	FName Mood;
	float MoodWeight = 0.f;
	FString Subtitle;
	double SubtitleUntil = 0.0;
	int32 LinesPlayed = 0;
	float Exertion01 = 0.f;
	TArray<FName> MoodMorphs;          // morphs touched by the mood layer (cleared when it decays)
	void ApplyBaseMood(float Smile, float Frown);
	float BaseSmile = 0.f, BaseFrown = 0.f;
	bool bBaseMoodApplied = false;
};
