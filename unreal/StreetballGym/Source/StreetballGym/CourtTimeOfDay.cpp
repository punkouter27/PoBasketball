#include "CourtTimeOfDay.h"
#include "StreetballGym.h"
#include "StreetballShowcase.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY_STATIC(LogCourtTimeOfDay, Log, All);

namespace
{
	float Smooth(float A, float B, float X) { return FMath::SmoothStep(A, B, X); }
	const FLinearColor MoonColor(0.55f, 0.68f, 1.0f);
	const FLinearColor DuskColor(1.0f, 0.55f, 0.3f);
	constexpr float MoonPitchDeg = -38.f;
	constexpr float MoonLightFraction = 0.06f; // moonlight vs the level's sun (auto exposure lifts it)
}

// ---------------------------------------------------------------------------- sky model
FCourtSkyState FCourtSkyState::Evaluate(float H, float MaxElev, float RefHour, float RefYaw, float LampsOn, float LampsOff)
{
	FCourtSkyState S;
	H = FMath::Fmod(FMath::Fmod(H, 24.f) + 24.f, 24.f);
	// sunrise 06:00, noon at MaxElev, sunset 18:00; below the horizon at night (symmetric)
	S.SunElevationDeg = MaxElev * FMath::Sin(PI * (H - 6.f) / 12.f);
	const float E = S.SunElevationDeg;
	S.bMoon = E < -3.f; // handover at zero light: the sun has faded out by -3 deg, the moon fades in below it
	if (!S.bMoon)
	{
		S.LightPitchDeg = -FMath::Max(E, 2.f); // keep a grazing angle at the horizon: never light from below
		S.LightYawDeg = RefYaw + (H - RefHour) * 15.f;
		S.LightScale = Smooth(-3.f, 8.f, E);
		// warm near the horizon, white above ~20 deg
		S.LightColor = FMath::Lerp(DuskColor, FLinearColor::White, Smooth(0.f, 20.f, E));
	}
	else
	{
		S.LightPitchDeg = MoonPitchDeg;
		S.LightYawDeg = RefYaw + 180.f;
		S.LightScale = MoonLightFraction * (1.f - Smooth(-9.f, -3.f, E)); // rises as the sun sinks from -3 to -9 deg
		S.LightColor = MoonColor;
	}
	S.SkyScale = FMath::Lerp(0.04f, 1.f, Smooth(-10.f, 10.f, E));
	S.NightBlend = 1.f - Smooth(-8.f, 4.f, E);
	// lamps fade in over 15 min at LampsOn and out over 15 min before LampsOff (the night wraps past midnight)
	const float Fade = 0.25f;
	float On;
	if (LampsOn > LampsOff) On = (H >= LampsOn || H < LampsOff) ? 1.f : 0.f;
	else On = (H >= LampsOn && H < LampsOff) ? 1.f : 0.f;
	if (On > 0.f)
	{
		const float SinceOn = FMath::Fmod(H - LampsOn + 24.f, 24.f);
		const float UntilOff = FMath::Fmod(LampsOff - H + 24.f, 24.f);
		On = FMath::Min(FMath::Clamp(SinceOn / Fade, 0.f, 1.f), FMath::Clamp(UntilOff / Fade, 0.f, 1.f));
	}
	S.LampScale = On;
	return S;
}

float FCourtSkyState::AfternoonHourForElevation(float ElevationDeg, float MaxElev)
{
	const float X = FMath::Clamp(ElevationDeg / FMath::Max(MaxElev, 1.f), -1.f, 1.f);
	return 18.f - 12.f * FMath::Asin(X) / PI; // the afternoon branch of Evaluate's sine
}

// ---------------------------------------------------------------------------- subsystem
bool UCourtTimeOfDaySubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return !IsRunningCommandlet() && Super::ShouldCreateSubsystem(Outer);
}

bool UCourtTimeOfDaySubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

TStatId UCourtTimeOfDaySubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UCourtTimeOfDaySubsystem, STATGROUP_Tickables);
}

void UCourtTimeOfDaySubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	const UStreetballShowcaseConfig* Cfg = UStreetballShowcaseSettings::GetShowcaseConfig();
	if (!Cfg->bTimeOfDay && !FParse::Param(FCommandLine::Get(), TEXT("TimeOfDay"))) return;
	FindLights(InWorld);
	if (!Sun.IsValid())
	{
		UE_LOG(LogCourtTimeOfDay, Warning, TEXT("Time of day: no movable directional light in the level; off"));
		return;
	}
	MaxElevationDeg = Cfg->NoonElevationDeg;
	LampLumens = Cfg->LampLumens;
	LampsOnHour = Cfg->LampsOnHour;
	LampsOffHour = Cfg->LampsOffHour;
	// the level's own sun defines the start: same elevation on the afternoon side, same azimuth
	const FRotator R = Sun->GetComponentRotation();
	RefYawDeg = R.Yaw;
	RefHour = FCourtSkyState::AfternoonHourForElevation(-R.Pitch, MaxElevationDeg);
	Hour = Cfg->StartHour >= 0.f ? Cfg->StartHour : RefHour;
	FParse::Value(FCommandLine::Get(), TEXT("TimeOfDay="), Hour);
	bFrozen = FParse::Param(FCommandLine::Get(), TEXT("TimeOfDayFreeze"));
	HoursPerSecond = Cfg->DayLengthMinutes > 0.f ? 24.f / (Cfg->DayLengthMinutes * 60.f) : 0.f;
	{
		FActorSpawnParameters P;
		P.Name = TEXT("CourtNightExposure");
		NightExposure = InWorld.SpawnActor<APostProcessVolume>(APostProcessVolume::StaticClass(), FTransform::Identity, P);
		NightExposure->bUnbound = true;
		NightExposure->Priority = 10.f;
		FPostProcessSettings& PP = NightExposure->Settings;
		PP.bOverride_AutoExposureMinBrightness = PP.bOverride_AutoExposureMaxBrightness = true;
		PP.AutoExposureMinBrightness = PP.AutoExposureMaxBrightness = Cfg->NightExposureEV100; // fixed: night stays night
	}
	bLampsPending = !CreateLamps(InWorld);
	bReady = true;
	Apply();
	UE_LOG(LogCourtTimeOfDay, Log, TEXT("Time of day: start %.2f h (level sun = %.2f h), %s, %d streetlights"),
		Hour, RefHour, bFrozen || HoursPerSecond <= 0.f ? TEXT("frozen") : *FString::Printf(TEXT("%.1f min per day"), Cfg->DayLengthMinutes), Lamps.Num());
}

void UCourtTimeOfDaySubsystem::FindLights(UWorld& World)
{
	for (TActorIterator<AActor> It(&World); It; ++It)
	{
		if (!Sun.IsValid())
			if (UDirectionalLightComponent* D = It->FindComponentByClass<UDirectionalLightComponent>())
				if (D->Mobility == EComponentMobility::Movable) { Sun = D; SunLux = D->Intensity; SunColor = D->LightColor; }
		if (!Sky.IsValid())
			if (USkyLightComponent* K = It->FindComponentByClass<USkyLightComponent>()) { Sky = K; SkyIntensity = K->Intensity; }
	}
}

void UCourtTimeOfDaySubsystem::ScanLamps(float DeltaTime)
{
	LampScanClock += DeltaTime;
	if (LampScanClock < LampScanNext) return;
	LampScanNext = LampScanClock + LampScanInterval;
	UWorld* World = GetWorld();
	if (World && CreateLamps(*World))
	{
		bLampsPending = false;
		Apply();
		UE_LOG(LogCourtTimeOfDay, Log, TEXT("Time of day: %d streetlights after %.1f s (PCG generated)"), Lamps.Num(), LampScanClock);
	}
	else if (LampScanClock > LampScanTimeout)
	{
		bLampsPending = false;
		UE_LOG(LogCourtTimeOfDay, Warning, TEXT("Time of day: no SM_StreetLight instances after %.0f s; no lamps"), LampScanTimeout);
	}
}

void UCourtTimeOfDaySubsystem::CollectLampHeads(UWorld& World, TArray<FVector>& Heads) const
{
	// The PCG graph places SM_StreetLight as instanced meshes; the lamp head is at LampLocalOffsetCm in the mesh's space.
	const UStreetballShowcaseConfig* Cfg = UStreetballShowcaseSettings::GetShowcaseConfig();
	for (TActorIterator<AActor> It(&World); It; ++It)
	{
		TArray<UInstancedStaticMeshComponent*> Ism;
		It->GetComponents(Ism);
		for (const UInstancedStaticMeshComponent* C : Ism)
		{
			if (!C->GetStaticMesh() || !C->GetStaticMesh()->GetName().Contains(TEXT("StreetLight"))) continue;
			for (int32 i = 0; i < C->GetInstanceCount(); ++i)
			{
				FTransform T;
				if (C->GetInstanceTransform(i, T, /*bWorldSpace*/ true)) Heads.Add(T.TransformPosition(Cfg->LampLocalOffsetCm));
			}
		}
	}
}

bool UCourtTimeOfDaySubsystem::CreateLamps(UWorld& World)
{
	// One spot light per streetlight instance, allocated once (no spawning while running), and only once the PCG
	// output has stopped growing: the same non-zero count on 3 scans in a row (1 s at LampScanInterval 0.5 s).
	TArray<FVector> Heads;
	CollectLampHeads(World, Heads);
	StableScans = (Heads.Num() > 0 && Heads.Num() == LastHeadCount) ? StableScans + 1 : 0;
	LastHeadCount = Heads.Num();
	if (StableScans < 2) return false;
	FActorSpawnParameters P;
	P.Name = TEXT("CourtStreetlights");
	LampHolder = World.SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, P);
	USceneComponent* Root = NewObject<USceneComponent>(LampHolder, TEXT("Root"));
	LampHolder->SetRootComponent(Root);
	Root->RegisterComponent();
	Lamps.Reserve(Heads.Num());
	for (int32 i = 0; i < Heads.Num(); ++i)
	{
		USpotLightComponent* L = NewObject<USpotLightComponent>(LampHolder, *FString::Printf(TEXT("Streetlight%02d"), i));
		L->SetMobility(EComponentMobility::Movable);
		L->SetupAttachment(Root);
		L->SetWorldLocationAndRotation(Heads[i], FRotator(-90.f, 0.f, 0.f));
		L->IntensityUnits = ELightUnits::Lumens;
		L->SetIntensity(0.f);
		L->SetLightColor(FLinearColor(1.0f, 0.78f, 0.5f)); // sodium-ish warm white
		L->SetInnerConeAngle(35.f);
		L->SetOuterConeAngle(62.f);
		L->SetAttenuationRadius(2200.f);
		L->SetSourceRadius(15.f);
		L->SetCastShadows(true);
		L->bAllowMegaLights = true;
		L->MegaLightsShadowMethod = EMegaLightsShadowMethod::VirtualShadowMap; // no hardware ray tracing in this project
		L->SetVisibility(false);
		L->RegisterComponent();
		Lamps.Add(L);
	}
	return true;
}

void UCourtTimeOfDaySubsystem::SetHour(float InHour)
{
	Hour = FMath::Fmod(FMath::Fmod(InHour, 24.f) + 24.f, 24.f);
	if (bReady) Apply();
}

void UCourtTimeOfDaySubsystem::Tick(float DeltaTime)
{
	if (bLampsPending) ScanLamps(DeltaTime);
	if (bFrozen || HoursPerSecond <= 0.f) return;
	Hour = FMath::Fmod(Hour + DeltaTime * HoursPerSecond, 24.f);
	Apply();
}

void UCourtTimeOfDaySubsystem::Apply()
{
	State = FCourtSkyState::Evaluate(Hour, MaxElevationDeg, RefHour, RefYawDeg, LampsOnHour, LampsOffHour);
	if (UDirectionalLightComponent* D = Sun.Get())
	{
		D->SetWorldRotation(FRotator(State.LightPitchDeg, State.LightYawDeg, 0.f));
		D->SetIntensity(SunLux * State.LightScale);
		D->SetLightColor(SunColor * State.LightColor);
		// the moon must not drive the atmosphere (it would paint a daylight sky); the sun does
		D->SetAtmosphereSunLight(!State.bMoon);
	}
	if (USkyLightComponent* K = Sky.Get()) K->SetIntensity(SkyIntensity * State.SkyScale);
	if (NightExposure) NightExposure->BlendWeight = State.NightBlend;
	const bool bOn = State.LampScale > 0.001f;
	for (USpotLightComponent* L : Lamps)
	{
		if (!L) continue;
		if (L->IsVisible() != bOn) L->SetVisibility(bOn);
		if (bOn) L->SetIntensity(LampLumens * State.LampScale);
	}
}
