// Po Game Standard C9/C10 (editor-first config), C12 (overlay + sim benchmark) and C13 (idle demo mode).
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "StreetballGym.h"
#include "StreetballShowcase.h"
#include "StreetballRewardConfig.h"
#include "StreetballHUDWidget.h"
#include "Blueprint/UserWidget.h"
#include "MuJoCoSim.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	constexpr EAutomationTestFlags SFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

	struct FScopedShowcaseWorld
	{
		UWorld* World = nullptr;
		FScopedShowcaseWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("StreetballShowcaseTestWorld"));
			FWorldContext& Ctx = GEngine->CreateNewWorldContext(EWorldType::Game);
			Ctx.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
			World->BeginPlay();
		}
		~FScopedShowcaseWorld()
		{
			if (World) { GEngine->DestroyWorldContext(World); World->DestroyWorld(false); }
		}
	};

	void Advance(UStreetballShowcaseSubsystem* S, float Seconds, float Frame)
	{
		for (float T = 0.f; T < Seconds - 1e-4f; T += Frame) S->AdvanceClocks(Frame);
	}
}

// ---------------------------------------------------------------------------- C13: idle clock
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballShowcaseIdleTest, "Streetball.Showcase.IdleDemoIgnoresLongFrames", SFlags)
bool FStreetballShowcaseIdleTest::RunTest(const FString&)
{
	FScopedShowcaseWorld TW;
	UStreetballShowcaseSubsystem* S = UStreetballShowcaseSubsystem::Get(TW.World);
	if (!TestNotNull(TEXT("showcase subsystem in a game world"), S)) return false;
	const float Threshold = UStreetballShowcaseSettings::GetShowcaseConfig()->IdleSeconds;
	TestEqual(TEXT("idle threshold is 30 s"), Threshold, 30.f);

	// A 70 s hitch (e.g. shader warm-up) is not idle time.
	S->AdvanceClocks(70.f);
	TestFalse(TEXT("no demo after one 70 s frame"), S->IsDemoActive());
	TestTrue(TEXT("idle clock ignored the long frame"), S->GetIdleSeconds() < 0.01f);

	// 20 s of normal frames: still the menu / game.
	Advance(S, 20.f, 1.f / 60.f);
	TestFalse(TEXT("no demo at 20 s"), S->IsDemoActive());
	// another 11 s: demo is on.
	Advance(S, 11.f, 1.f / 60.f);
	TestTrue(TEXT("demo at 31 s idle"), S->IsDemoActive());
	// any input returns control.
	S->NotifyUserInput();
	TestFalse(TEXT("input ends demo"), S->IsDemoActive());
	TestTrue(TEXT("input restarts the idle clock"), S->GetIdleSeconds() < 0.01f);
	return true;
}

// ---------------------------------------------------------------------------- C12: overlay + benchmark
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballShowcaseBenchmarkTest, "Streetball.Showcase.OverlayAndSimBenchmark", SFlags)
bool FStreetballShowcaseBenchmarkTest::RunTest(const FString&)
{
	// The bounded step loop on its own.
	UMuJoCoSim* Sim = NewObject<UMuJoCoSim>(GetTransientPackage());
	Sim->AddToRoot();
	if (!TestTrue(TEXT("scene.xml loads"), Sim->LoadXml(Streetball::SceneXmlPath()))) { Sim->RemoveFromRoot(); return false; }
	Sim->ResetToKeyframe(TEXT("stand"));
	const FStreetballSimBenchmark B = UStreetballShowcaseSubsystem::StepForBudget(Sim, 0.25);
	Sim->Unload();
	Sim->RemoveFromRoot();
	AddInfo(FString::Printf(TEXT("%d steps in %.3f s = %.0f steps/s (%.1fx real time)"), B.Steps, B.WallSeconds, B.StepsPerSecond(), B.RealTimeFactor()));
	TestTrue(TEXT("stepped"), B.Steps > 0);
	TestTrue(TEXT("bounded by the budget (+1 batch)"), B.WallSeconds < 1.0);
	TestTrue(TEXT("sim time = steps x 2 ms"), FMath::IsNearlyEqual(B.SimSeconds, B.Steps * 0.002, 1e-6));
	const FString Text = UStreetballShowcaseSubsystem::FormatBenchmark(B);
	TestTrue(TEXT("labelled as physics steps/s"), Text.Contains(TEXT("physics steps/s")));
	TestTrue(TEXT("labelled as a CPU proxy, not the trainer"), Text.Contains(TEXT("CPU MuJoCo")) && Text.Contains(TEXT("MuJoCo Warp on the GPU")));

	// Through the subsystem, as the overlay button / key does it.
	FScopedShowcaseWorld TW;
	UStreetballShowcaseSubsystem* S = UStreetballShowcaseSubsystem::Get(TW.World);
	if (!TestNotNull(TEXT("showcase subsystem"), S)) return false;
	const FString Before = S->BuildOverlayText();
	for (const TCHAR* Row : { TEXT("FPS"), TEXT("Episode reward"), TEXT("Inference latency"), TEXT("Curriculum stage"), TEXT("Sim benchmark") })
	{
		TestTrue(FString::Printf(TEXT("overlay shows %s"), Row), Before.Contains(Row));
	}
	S->StartBenchmark();
	TestTrue(TEXT("benchmark running"), S->IsBenchmarkRunning());
	TestTrue(TEXT("overlay says running"), S->BuildOverlayText().Contains(TEXT("running")));
	TestTrue(TEXT("benchmark collected"), S->PollBenchmark(/*bWait*/ true));
	TestFalse(TEXT("benchmark finished"), S->IsBenchmarkRunning());
	TestTrue(TEXT("overlay shows the result"), S->BuildOverlayText().Contains(TEXT("physics steps/s")));
	AddInfo(S->GetBenchmarkResult());
	return true;
}

// ---------------------------------------------------------------------------- C11: 16:9 and 9:16
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballHUDLayoutTest, "Streetball.Showcase.HUDLayoutLandscapeAndPortrait", SFlags)
bool FStreetballHUDLayoutTest::RunTest(const FString&)
{
	FScopedShowcaseWorld TW;
	UStreetballHUDWidget* HUD = CreateWidget<UStreetballHUDWidget>(TW.World, UStreetballHUDWidget::StaticClass());
	if (!TestNotNull(TEXT("widget"), HUD)) return false;
	HUD->TakeWidget();
	HUD->ApplyLayout(FVector2D(1600.f, 900.f));
	TestFalse(TEXT("16:9 uses the corner layout"), HUD->IsNarrowLayout());
	HUD->ApplyLayout(FVector2D(450.f, 800.f));
	TestTrue(TEXT("9:16 stacks and wraps"), HUD->IsNarrowLayout());
	HUD->ApplyLayout(FVector2D(1366.f, 768.f));
	TestFalse(TEXT("back to landscape"), HUD->IsNarrowLayout());
	return true;
}

// ---------------------------------------------------------------------------- C9/C10: DataAssets
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballShowcaseConfigAssetsTest, "Streetball.Showcase.ConfigDataAssets", SFlags)
bool FStreetballShowcaseConfigAssetsTest::RunTest(const FString&)
{
	const UStreetballShowcaseConfig* Show = UStreetballShowcaseSettings::GetShowcaseConfig();
	const UStreetballRewardConfig* Reward = UStreetballShowcaseSettings::GetRewardConfig();
	TestEqual(TEXT("showcase config is the DataAsset"), Show->GetPathName(), FString(TEXT("/Game/Project/DataAssets/DA_ShowcaseConfig.DA_ShowcaseConfig")));
	TestEqual(TEXT("reward config is the DataAsset"), Reward->GetPathName(), FString(TEXT("/Game/Project/DataAssets/DA_RewardConfig.DA_RewardConfig")));
	TestTrue(TEXT("demo cameras listed"), Show->DemoCameras.Num() >= 1);

	// The asset in use must match what the trainer reads.
	FString Json;
	const FString Path = FPaths::Combine(Streetball::RepoSharedDir(), TEXT("reward_config.json"));
	TSharedPtr<FJsonObject> Cfg;
	if (!TestTrue(TEXT("read shared/reward_config.json"), FFileHelper::LoadFileToString(Json, *Path)
		&& FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Cfg) && Cfg.IsValid())) return false;
	const TSharedPtr<FJsonObject> Pen = Cfg->GetObjectField(TEXT("penalties"));
	// the asset stores float32: compare to the JSON double within float precision
	auto SameWeight = [this, &Pen](const TCHAR* Term, float Asset)
	{
		const double Want = Pen->GetNumberField(Term);
		TestEqual(Term, (double)Asset, Want, FMath::Max(1e-12, FMath::Abs(Want) * 1e-6));
	};
	SameWeight(TEXT("torque_sq"), Reward->TorqueSqWeight);
	SameWeight(TEXT("joint_ang_vel_sq"), Reward->JointAngVelSqWeight);
	SameWeight(TEXT("action_rate_sq"), Reward->ActionRateSqWeight);
	SameWeight(TEXT("foot_slip"), Reward->FootSlipWeight);
	const TArray<TSharedPtr<FJsonValue>>& Stages = Cfg->GetArrayField(TEXT("curriculum"));
	if (TestEqual(TEXT("curriculum stage count"), Reward->CurriculumStages.Num(), Stages.Num()))
	{
		for (int32 i = 0; i < Stages.Num(); ++i)
		{
			const TSharedPtr<FJsonObject> Row = Stages[i]->AsObject();
			TestEqual(TEXT("stage name"), Reward->CurriculumStages[i].Stage, Row->GetStringField(TEXT("stage")));
			TestEqual(TEXT("stage threshold"), (double)Reward->CurriculumStages[i].Threshold, Row->GetNumberField(TEXT("threshold")), 1e-6);
		}
	}
	return true;
}

#endif
