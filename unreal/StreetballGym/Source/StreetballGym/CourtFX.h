#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "CourtAudio.h"
#include "PresentationEvents.h"
#include "CourtFX.generated.h"

class UNiagaraSystem;
class UNiagaraComponent;
class UStaticMesh;
class UMaterialInterface;
class UMaterialInstanceDynamic;
class UStaticMeshComponent;
class AActor;

/** Which pooled effect a cue fires. */
enum class ECourtFX : uint8
{
	BallDust,       // ball hits the asphalt
	RimSparks,      // hard rim hit
	BoardDust,      // backboard thud (chalk/dust puff)
	Swish,          // net burst on a make
	FootDust,       // hard cut / slide
	Sweat,          // sweat flick after long scrambles / jump shots
	Count
};

/** Niagara systems for event bursts and ambience (Scripts/make_niagara_fx.py). Missing entries are skipped. */
UCLASS(BlueprintType)
class STREETBALLGYM_API UCourtFXBank : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bursts") TObjectPtr<UNiagaraSystem> BallDust;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bursts") TObjectPtr<UNiagaraSystem> RimSparks;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bursts") TObjectPtr<UNiagaraSystem> BoardDust;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bursts") TObjectPtr<UNiagaraSystem> Swish;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bursts") TObjectPtr<UNiagaraSystem> FootDust;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bursts") TObjectPtr<UNiagaraSystem> Sweat;
	/** Looping ambience placed once at startup (leaves, dust motes in the sun, pigeons). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ambience") TObjectPtr<UNiagaraSystem> Leaves;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ambience") TObjectPtr<UNiagaraSystem> Motes;
	/** One-shot pigeon flock that takes off when the ball lands near the perch. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ambience") TObjectPtr<UNiagaraSystem> Pigeons;
	/** Visual net under each rim (no collision, not in the sim). Material reads SwishTime / HitTime. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Net") TObjectPtr<UStaticMesh> NetMesh;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Net") TObjectPtr<UMaterialInterface> NetMaterial;

	/** Ball-floor impacts below this speed (m/s) make no dust. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mapping") float DustMinSpeed = 1.5f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mapping") float SparkMinSpeed = 3.0f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mapping") float FootDustMinSpeed = 1.2f;

	UNiagaraSystem* SystemFor(ECourtFX Fx) const;
};

/** A burst to fire: pure data so the mapping is testable without a world. */
struct STREETBALLGYM_API FCourtFXCue
{
	ECourtFX Fx = ECourtFX::BallDust;
	EStreetballSurface Surface = EStreetballSurface::Unknown;
	FVector PositionUE = FVector::ZeroVector;
	FVector NormalUE = FVector::UpVector;
	float Scale = 1.f;
	float ImpactSpeed = 0.f;
};

struct STREETBALLGYM_API FCourtFXMapping
{
	float DustMinSpeed = 1.5f, SparkMinSpeed = 3.0f, FootDustMinSpeed = 1.2f, SpeedForFull = 8.f;
	/** Contact event -> burst (false: no effect for this event). */
	bool FromAudioEvent(const FCourtAudioEvent& E, FCourtFXCue& Out) const;
};

/**
 * Pre-allocated Niagara pools (no spawning after setup, UU_AGENT allocation rule), the two visual nets and the
 * ambience emitters. Reads events only.
 */
class STREETBALLGYM_API FCourtFXPlayer
{
public:
	/** RimCentersUE: east, west rim centres in UE cm. */
	void Initialize(AActor* Owner, UCourtFXBank* InBank, const FVector RimCentersUE[2], int32 PoolPerFx = 4);
	void Play(const FCourtFXCue& Cue);
	/** Net reaction (Swish = ball through the net, Hit = rim/board knock) at game time Now. */
	void KickNet(int32 RimIndex, bool bSwish, double Now, float Intensity = 1.f);
	/** Pigeons take off when the ball lands within PerchRadius of the perch (once per Cooldown). */
	void NotifyBallLanding(const FVector& BallUE, double Now);

	bool HasBank() const { return Bank.IsValid(); }
	int32 PlayedCount = 0;
	int32 NetKicks = 0;
	FVector PerchUE = FVector(1200.0, 1050.0, 0.0);
	float PerchRadius = 700.f;
	double PigeonCooldown = 25.0;
	const FCourtFXMapping& GetMapping() const { return Mapping; }

private:
	TWeakObjectPtr<UCourtFXBank> Bank;
	TArray<TWeakObjectPtr<UNiagaraComponent>> Pools[(int32)ECourtFX::Count];
	int32 Next[(int32)ECourtFX::Count] = {0};
	TWeakObjectPtr<UNiagaraComponent> PigeonComp;
	TWeakObjectPtr<UMaterialInstanceDynamic> NetMID[2];
	double LastPigeonT = -1000.0;
	FCourtFXMapping Mapping;
};
