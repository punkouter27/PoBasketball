// Time of day for the court (2026-11-24): the sun crosses the sky, dusk turns into a moonlit night and the 17 PCG
// streetlights switch on. Presentation only: nothing here touches MuJoCo (UU_AGENT §1, engine = render layer).
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "CourtTimeOfDay.generated.h"

class UDirectionalLightComponent;
class USkyLightComponent;
class USpotLightComponent;
class AActor;
class APostProcessVolume;

/** Sun / moon / sky / lamps for one hour of the day. Pure math, so tests can check it without a world. */
struct STREETBALLGYM_API FCourtSkyState
{
	float SunElevationDeg = 0.f;   // > 0 above the horizon
	float LightPitchDeg = 0.f;     // directional light pitch (negative = pointing down)
	float LightYawDeg = 0.f;
	float LightScale = 1.f;        // x the level's sun intensity (the same light is the moon at night)
	FLinearColor LightColor = FLinearColor::White;
	float SkyScale = 1.f;          // x the level's sky light intensity
	float LampScale = 0.f;         // 0 = off, 1 = full
	float NightBlend = 0.f;        // weight of the night exposure (0 by day, 1 once the sun is 8 deg below the horizon)
	bool bMoon = false;

	/** Hour in [0, 24). MaxElevationDeg: noon elevation. RefHour/RefYawDeg: the azimuth the level was lit with. */
	static FCourtSkyState Evaluate(float Hour, float MaxElevationDeg, float RefHour, float RefYawDeg, float LampsOnHour, float LampsOffHour);
	/** Hour (on the afternoon side) at which the sun stands at ElevationDeg. */
	static float AfternoonHourForElevation(float ElevationDeg, float MaxElevationDeg);
};

UCLASS()
class STREETBALLGYM_API UCourtTimeOfDaySubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "TimeOfDay") void SetHour(float InHour);
	UFUNCTION(BlueprintPure, Category = "TimeOfDay") float GetHour() const { return Hour; }
	UFUNCTION(BlueprintPure, Category = "TimeOfDay") int32 NumLamps() const { return Lamps.Num(); }
	UFUNCTION(BlueprintPure, Category = "TimeOfDay") bool AreLampsOn() const { return State.LampScale > 0.01f; }
	const FCourtSkyState& GetState() const { return State; }

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bReady; }

protected:
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
	void Apply();
	void FindLights(UWorld& World);
	/** True once lamps exist (or the scan gave up). PCG generates the neighbourhood over the first frames after
	 *  BeginPlay (GenerateOnLoad), so the scan is retried every LampScanInterval s for LampScanTimeout s. */
	bool CreateLamps(UWorld& World);
	void CollectLampHeads(UWorld& World, TArray<FVector>& Out) const;
	int32 LastHeadCount = -1, StableScans = 0;
	void ScanLamps(float DeltaTime);

	bool bReady = false;
	bool bFrozen = false;
	bool bLampsPending = false;
	float LampScanClock = 0.f, LampScanNext = 0.f;
	float LampScanInterval = 0.5f, LampScanTimeout = 30.f;
	float Hour = 13.6f;
	float HoursPerSecond = 0.f;
	float RefHour = 13.6f, RefYawDeg = 35.f, MaxElevationDeg = 60.f;
	float SunLux = 10.f, SkyIntensity = 1.f;
	FLinearColor SunColor = FLinearColor::White;
	float LampLumens = 6000.f, LampsOnHour = 17.9f, LampsOffHour = 6.1f;
	FCourtSkyState State;
	TWeakObjectPtr<UDirectionalLightComponent> Sun;
	TWeakObjectPtr<USkyLightComponent> Sky;
	UPROPERTY(Transient) TObjectPtr<AActor> LampHolder;
	/** Unbound volume holding the night exposure; its blend weight follows FCourtSkyState::NightBlend. Without it, auto
	 *  exposure lifts a moonlit court back to overcast-day brightness. */
	UPROPERTY(Transient) TObjectPtr<APostProcessVolume> NightExposure;
	UPROPERTY(Transient) TArray<TObjectPtr<USpotLightComponent>> Lamps;
};
