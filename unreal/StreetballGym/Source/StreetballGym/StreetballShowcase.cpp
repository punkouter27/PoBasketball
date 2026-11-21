#include "StreetballShowcase.h"

#include "StreetballRewardConfig.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/PlatformMisc.h"
#include "InputCoreTypes.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Paths.h"
#include "Misc/Parse.h"
#include "Styling/CoreStyle.h"
#include "UnrealClient.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(StreetballShowcase)

DEFINE_LOG_CATEGORY_STATIC(LogStreetballShowcase, Log, All);

namespace StreetballShowcaseUi
{
	// Po Game Standard tokens: opaque surface panel, text >= 4.5:1 on it (#e6e9f2 on #121826 is ~14:1).
	static FLinearColor Hex(const TCHAR* H) { return FLinearColor::FromSRGBColor(FColor::FromHex(H)); }
	static FLinearColor Surface() { return Hex(TEXT("121826")); }
	static FLinearColor Text() { return Hex(TEXT("e6e9f2")); }
	static FLinearColor Muted() { return Hex(TEXT("9aa3b5")); }
	static FLinearColor Accent() { return Hex(TEXT("6366f1")); }
}

// ------------------------------------------------------------------------------------------------------------
// Input: every key, button, touch, wheel, real mouse move and gamepad stick counts as "the player is here".

class FStreetballShowcaseInput : public IInputProcessor
{
public:
	FStreetballShowcaseInput(UStreetballShowcaseSubsystem* InOwner, const FKey& InToggleKey) : Owner(InOwner), ToggleKey(InToggleKey) {}

	virtual void Tick(const float DeltaTime, FSlateApplication& SlateApp, TSharedRef<ICursor> Cursor) override {}

	virtual bool HandleKeyDownEvent(FSlateApplication& SlateApp, const FKeyEvent& InKeyEvent) override
	{
		UStreetballShowcaseSubsystem* O = Owner.Get();
		if (!O) return false;
		O->NotifyUserInput();
		if (InKeyEvent.GetKey() == ToggleKey)
		{
			if (!InKeyEvent.IsRepeat()) O->ToggleOverlay();
			return true;   // the overlay owns its key
		}
		return false;
	}

	virtual bool HandleAnalogInputEvent(FSlateApplication& SlateApp, const FAnalogInputEvent& InAnalogInputEvent) override
	{
		if (FMath::Abs(InAnalogInputEvent.GetAnalogValue()) > 0.25f) Touch();
		return false;
	}

	virtual bool HandleMouseMoveEvent(FSlateApplication& SlateApp, const FPointerEvent& MouseEvent) override
	{
		if (MouseEvent.GetCursorDelta().SizeSquared() > 4.f) Touch();   // synthetic moves carry no delta
		return false;
	}

	virtual bool HandleMouseButtonDownEvent(FSlateApplication& SlateApp, const FPointerEvent& MouseEvent) override
	{
		Touch();   // mouse buttons and touches
		return false;
	}

	virtual bool HandleMouseWheelOrGestureEvent(FSlateApplication& SlateApp, const FPointerEvent& InWheelEvent, const FPointerEvent* InGestureEvent) override
	{
		Touch();
		return false;
	}

	virtual const TCHAR* GetDebugName() const override { return TEXT("StreetballShowcase"); }

private:
	void Touch() { if (UStreetballShowcaseSubsystem* O = Owner.Get()) O->NotifyUserInput(); }

	TWeakObjectPtr<UStreetballShowcaseSubsystem> Owner;
	FKey ToggleKey;
};

// ------------------------------------------------------------------------------------------------------------

UStreetballShowcaseConfig::UStreetballShowcaseConfig()
{
	OverlayKey = EKeys::Tab;
	DemoCameras = { FName(TEXT("Broadcast")), FName(TEXT("Follow")), FName(TEXT("Orbit")) };
}

const UStreetballShowcaseConfig* UStreetballShowcaseSettings::GetShowcaseConfig()
{
	const UStreetballShowcaseSettings* S = GetDefault<UStreetballShowcaseSettings>();
	if (S && !S->ShowcaseConfig.IsNull())
	{
		if (const UStreetballShowcaseConfig* Asset = S->ShowcaseConfig.LoadSynchronous()) return Asset;
	}
	return GetDefault<UStreetballShowcaseConfig>();
}

const UStreetballRewardConfig* UStreetballShowcaseSettings::GetRewardConfig()
{
	const UStreetballShowcaseSettings* S = GetDefault<UStreetballShowcaseSettings>();
	if (S && !S->RewardConfig.IsNull())
	{
		if (const UStreetballRewardConfig* Asset = S->RewardConfig.LoadSynchronous()) return Asset;
	}
	return GetDefault<UStreetballRewardConfig>();
}

// ------------------------------------------------------------------------------------------------------------

UStreetballShowcaseSubsystem* UStreetballShowcaseSubsystem::Get(const UObject* WorldContext)
{
	const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UStreetballShowcaseSubsystem>() : nullptr;
}

bool UStreetballShowcaseSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return !IsRunningCommandlet() && Super::ShouldCreateSubsystem(Outer);
}

bool UStreetballShowcaseSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void UStreetballShowcaseSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	const UStreetballShowcaseConfig* Cfg = UStreetballShowcaseSettings::GetShowcaseConfig();
	IdleThreshold = Cfg->IdleSeconds;
	FParse::Value(FCommandLine::Get(), TEXT("ShowcaseIdle="), IdleThreshold);
	IdleThreshold = FMath::Max(1.f, IdleThreshold);
	LatencySamples.Reset();
	bOverlayVisible = FParse::Param(FCommandLine::Get(), TEXT("DiagOverlay"));
	bTouchButton = Cfg->bTouchCornerButton
		&& (PLATFORM_ANDROID || PLATFORM_IOS || FPlatformMisc::GetUseVirtualJoysticks() || FParse::Param(FCommandLine::Get(), TEXT("ShowcaseTouch")));
	FString Dir;
	if (FParse::Value(FCommandLine::Get(), TEXT("ShowcaseCapture="), Dir)) CaptureDir = FPaths::ConvertRelativePathToFull(Dir);
}

void UStreetballShowcaseSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!FSlateApplication::IsInitialized()) return;
	const UStreetballShowcaseConfig* Cfg = UStreetballShowcaseSettings::GetShowcaseConfig();
	Input = MakeShared<FStreetballShowcaseInput>(this, Cfg->OverlayKey);
	FSlateApplication::Get().RegisterInputPreProcessor(Input);
	AddWidgets();
	UE_LOG(LogStreetballShowcase, Log, TEXT("Showcase: overlay key %s, demo after %.0f s idle, %d demo cameras, touch button %s%s"),
		*Cfg->OverlayKey.ToString(), IdleThreshold, Cfg->DemoCameras.Num(), bTouchButton ? TEXT("on") : TEXT("off"),
		CaptureDir.IsEmpty() ? TEXT("") : *FString::Printf(TEXT(", capturing to %s"), *CaptureDir));
}

void UStreetballShowcaseSubsystem::Deinitialize()
{
	if (Input.IsValid() && FSlateApplication::IsInitialized()) FSlateApplication::Get().UnregisterInputPreProcessor(Input);
	Input.Reset();
	RemoveWidgets();
	Super::Deinitialize();
}

TStatId UStreetballShowcaseSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UStreetballShowcaseSubsystem, STATGROUP_Tickables);
}

void UStreetballShowcaseSubsystem::AddWidgets()
{
	UWorld* World = GetWorld();
	UGameViewportClient* VC = World ? World->GetGameViewport() : nullptr;
	if (!VC) return;
	const TWeakObjectPtr<UStreetballShowcaseSubsystem> Weak(this);
	const FSlateFontInfo Mono = FCoreStyle::GetDefaultFontStyle("Mono", 13);
	const FSlateFontInfo Body = FCoreStyle::GetDefaultFontStyle("Regular", 13);
	const FSlateBrush* White = FCoreStyle::Get().GetBrush("WhiteBrush");

	OverlayWidget = SNew(SBox)
		.HAlign(HAlign_Left).VAlign(VAlign_Top).Padding(FMargin(16.f, 64.f, 16.f, 16.f))
		.Visibility_Lambda([Weak] { return Weak.IsValid() && Weak->IsOverlayVisible() && !Weak->IsDemoActive() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
		[
			SNew(SBorder).BorderImage(White).BorderBackgroundColor(StreetballShowcaseUi::Surface()).Padding(FMargin(14.f, 10.f))
			[
				SNew(STextBlock).Font(Mono).ColorAndOpacity(StreetballShowcaseUi::Text())
				.Text_Lambda([Weak] { return Weak.IsValid() ? FText::FromString(Weak->BuildOverlayText()) : FText::GetEmpty(); })
			]
		];
	VC->AddViewportWidgetContent(OverlayWidget.ToSharedRef(), 1000);

	DemoHintWidget = SNew(SBox)
		.HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(16.f, 16.f, 16.f, 40.f))
		.Visibility_Lambda([Weak] { return Weak.IsValid() && Weak->IsDemoActive() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
		[
			SNew(SBorder).BorderImage(White).BorderBackgroundColor(StreetballShowcaseUi::Surface()).Padding(FMargin(14.f, 8.f))
			[
				SNew(STextBlock).Font(Body).ColorAndOpacity(StreetballShowcaseUi::Text())
				.Text(NSLOCTEXT("StreetballShowcase", "DemoHint", "Demo  -  press any key or touch to play"))
			]
		];
	VC->AddViewportWidgetContent(DemoHintWidget.ToSharedRef(), 1000);

	if (bTouchButton)
	{
		ButtonWidget = SNew(SBox)
			.HAlign(HAlign_Right).VAlign(VAlign_Top).Padding(FMargin(8.f))
			.Visibility_Lambda([Weak] { return Weak.IsValid() && !Weak->IsDemoActive() ? EVisibility::SelfHitTestInvisible : EVisibility::Collapsed; })
			[
				SNew(SBox).WidthOverride(44.f).HeightOverride(44.f)
				[
					SNew(SButton)
					.ButtonColorAndOpacity(StreetballShowcaseUi::Accent())
					.HAlign(HAlign_Center).VAlign(VAlign_Center)
					.ToolTipText(NSLOCTEXT("StreetballShowcase", "ButtonTip", "Diagnostics"))
					.OnClicked_Lambda([Weak] { if (Weak.IsValid()) Weak->ToggleOverlay(); return FReply::Handled(); })
					[
						SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Bold", 15)).ColorAndOpacity(FLinearColor::White)
						.Text(NSLOCTEXT("StreetballShowcase", "ButtonLabel", "i"))
					]
				]
			];
		VC->AddViewportWidgetContent(ButtonWidget.ToSharedRef(), 1001);
	}
}

void UStreetballShowcaseSubsystem::RemoveWidgets()
{
	UWorld* World = GetWorld();
	UGameViewportClient* VC = World ? World->GetGameViewport() : nullptr;
	for (TSharedPtr<SWidget>* W : { &OverlayWidget, &DemoHintWidget, &ButtonWidget })
	{
		if (VC && W->IsValid()) VC->RemoveViewportWidgetContent(W->ToSharedRef());
		W->Reset();
	}
}

void UStreetballShowcaseSubsystem::ReportEpisodeReward(float Reward)
{
	EpisodeReward = Reward;
	bHaveReward = true;
}

void UStreetballShowcaseSubsystem::ReportInferenceMs(float Milliseconds)
{
	if (!FMath::IsFinite(Milliseconds) || Milliseconds < 0.f) return;
	const int32 Window = FMath::Clamp(UStreetballShowcaseSettings::GetShowcaseConfig()->LatencyWindow, 1, 600);
	if (LatencySamples.Num() < Window)
	{
		LatencySamples.Add(Milliseconds);
	}
	else
	{
		LatencySamples[LatencyNext % LatencySamples.Num()] = Milliseconds;
	}
	LatencyNext = (LatencyNext + 1) % Window;
}

void UStreetballShowcaseSubsystem::SetCurriculumStage(const FString& Stage)
{
	CurriculumStage = Stage;
}

float UStreetballShowcaseSubsystem::GetMeanInferenceMs() const
{
	if (LatencySamples.Num() == 0) return -1.f;
	float Sum = 0.f;
	for (const float V : LatencySamples) Sum += V;
	return Sum / LatencySamples.Num();
}

FString UStreetballShowcaseSubsystem::BuildOverlayText() const
{
	const UStreetballShowcaseConfig* Cfg = UStreetballShowcaseSettings::GetShowcaseConfig();
	const float Lat = GetMeanInferenceMs();
	FString Out = FString::Printf(TEXT("DIAGNOSTICS              [%s]\n"), *Cfg->OverlayKey.GetDisplayName().ToString());
	Out += FString::Printf(TEXT("FPS                      %.1f\n"), Fps);
	const FString Note = RewardNote.IsEmpty() ? FString() : FString::Printf(TEXT("  (%s)"), *RewardNote);
	Out += bHaveReward ? FString::Printf(TEXT("Episode reward           %.2f%s\n"), EpisodeReward, *Note) : FString(TEXT("Episode reward           n/a\n"));
	Out += Lat >= 0.f ? FString::Printf(TEXT("Inference latency        %.2f ms (mean of %d)\n"), Lat, LatencySamples.Num())
	                  : FString(TEXT("Inference latency        n/a (no policy step yet)\n"));
	Out += FString::Printf(TEXT("Curriculum stage         %s\n"), CurriculumStage.IsEmpty() ? TEXT("n/a") : *CurriculumStage);
	Out += FString::Printf(TEXT("Demo mode                after %.0f s idle (idle %.0f s)"), IdleThreshold, IdleTime);
	return Out;
}

void UStreetballShowcaseSubsystem::SetOverlayVisible(bool bVisible)
{
	bOverlayVisible = bVisible;
}

void UStreetballShowcaseSubsystem::NotifyUserInput()
{
	IdleTime = 0.f;
	if (bDemoActive) SetDemoActive(false);
}

void UStreetballShowcaseSubsystem::SetDemoActive(bool bActive)
{
	if (bDemoActive == bActive) return;
	bDemoActive = bActive;
	CameraTime = 0.f;
	CameraIndex = 0;
	UE_LOG(LogStreetballShowcase, Log, TEXT("Showcase: demo mode %s"), bActive ? TEXT("on (idle)") : TEXT("off (input)"));
	OnDemoModeChanged.Broadcast(bActive);
	const TArray<FName>& Cams = UStreetballShowcaseSettings::GetShowcaseConfig()->DemoCameras;
	if (bActive && Cams.Num() > 0) OnDemoCamera.Broadcast(Cams[0], 0);
}

void UStreetballShowcaseSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	const float Dt = static_cast<float>(FApp::GetDeltaTime());   // real time: pause and slow motion don't stop the idle clock
	if (Dt > 0.f)
	{
		const float Inst = 1.f / Dt;
		Fps = Fps <= 0.f ? Inst : FMath::Lerp(Fps, Inst, 0.05f);
	}
	IdleTime += Dt;
	if (!bDemoActive && IdleTime >= IdleThreshold) SetDemoActive(true);
	if (bDemoActive)
	{
		const UStreetballShowcaseConfig* Cfg = UStreetballShowcaseSettings::GetShowcaseConfig();
		CameraTime += Dt;
		if (Cfg->DemoCameras.Num() > 0 && CameraTime >= Cfg->CameraDwellSeconds)
		{
			CameraTime = 0.f;
			CameraIndex = (CameraIndex + 1) % Cfg->DemoCameras.Num();
			OnDemoCamera.Broadcast(Cfg->DemoCameras[CameraIndex], CameraIndex);
		}
	}
	if (!CaptureDir.IsEmpty()) TickCapture(Dt);
}

void UStreetballShowcaseSubsystem::Shot(const TCHAR* Name)
{
	const FString File = FPaths::Combine(CaptureDir, FString::Printf(TEXT("%s.png"), Name));
	FScreenshotRequest::RequestScreenshot(File, /*bShowUI*/ true, /*bAddFilenameSuffix*/ false);
	UE_LOG(LogStreetballShowcase, Log, TEXT("Showcase: screenshot %s (overlay %d, demo %d, idle %.1f s)"), *File, bOverlayVisible ? 1 : 0, bDemoActive ? 1 : 0, IdleTime);
}

void UStreetballShowcaseSubsystem::TickCapture(float Dt)
{
	// Scripted check of C12 / C13 without touching the input clock: overlay on, overlay off, demo mode after the
	// idle threshold (two shots one camera dwell apart), then quit.
	CaptureClock += Dt;
	const float Dwell = UStreetballShowcaseSettings::GetShowcaseConfig()->CameraDwellSeconds;
	const float DemoAt = IdleThreshold + 5.f;
	switch (CaptureStep)
	{
	case 0: if (CaptureClock >= 8.f) { SetOverlayVisible(true); ++CaptureStep; } break;
	case 1: if (CaptureClock >= 9.f) { Shot(TEXT("overlay_on")); ++CaptureStep; } break;
	case 2: if (CaptureClock >= 11.f) { SetOverlayVisible(false); ++CaptureStep; } break;
	case 3: if (CaptureClock >= 12.f) { Shot(TEXT("overlay_off")); ++CaptureStep; } break;
	case 4: if (CaptureClock >= DemoAt && bDemoActive) { Shot(TEXT("demo_a")); ++CaptureStep; } break;
	case 5: if (CaptureClock >= DemoAt + Dwell + 1.f) { Shot(TEXT("demo_b")); ++CaptureStep; } break;
	case 6: if (CaptureClock >= DemoAt + Dwell + 4.f)
		{
			UE_LOG(LogStreetballShowcase, Log, TEXT("Showcase: capture done (demo %d), exiting"), bDemoActive ? 1 : 0);
			++CaptureStep;
			FPlatformMisc::RequestExit(false, TEXT("ShowcaseCapture"));
		}
		break;
	default: break;
	}
}
