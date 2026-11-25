#include "StreetballHUDWidget.h"
#include "StreetballShowcase.h"
#include "UiTheme.h"
#include "Blueprint/WidgetTree.h"
#include "Components/TextBlock.h"
#include "Components/ProgressBar.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Rendering/DrawElements.h"
#include "Components/Border.h"
#include "Components/Button.h"
#include "Components/ButtonSlot.h"
#include "Framework/Application/SlateApplication.h"

// ---------------------------------------------------------------------------- Dribble Lab
void UStreetballHUDWidget::SetDribbleFocus(const TArray<FString>& Behaviours, const TArray<bool>& Trained, const TArray<FString>& Skins)
{
	UCanvasPanel* Canvas = WidgetTree ? Cast<UCanvasPanel>(WidgetTree->RootWidget) : nullptr;
	if (DribblePanel || !Canvas) return;
	using namespace StreetballUiTheme;
	BehaviourNames = Behaviours;
	BehaviourTrained = Trained;
	// the five-tier scoreboard and the mode banner are hidden, not removed (-StreetballClassicHUD brings them back)
	if (Root) Root->SetVisibility(ESlateVisibility::Collapsed);
	if (ModeBannerText) ModeBannerText->SetVisibility(ESlateVisibility::Collapsed);

	DribblePanel = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), TEXT("DribblePanel"));
	DribblePanel->SetBrushColor(PanelBg);
	DribblePanel->SetPadding(FMargin(Space4, Space3));
	DribblePanel->SetVisibility(ESlateVisibility::Visible);
	UCanvasPanelSlot* PS = Canvas->AddChildToCanvas(DribblePanel);
	PS->SetAnchors(FAnchors(0.f, 0.f));
	PS->SetPosition(FVector2D(SafeAreaMargin, SafeAreaMargin));
	PS->SetAutoSize(true);
	UVerticalBox* Box = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass(), TEXT("DribbleBox"));
	DribblePanel->SetContent(Box);

	auto AddText = [this, Box](const TCHAR* Name, const FString& Text, int32 Size, const FLinearColor& Color, float PadTop) -> UTextBlock*
	{
		UTextBlock* T = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), Name);
		FSlateFontInfo F = T->GetFont();
		F.Size = Size;
		T->SetFont(F);
		T->SetColorAndOpacity(FSlateColor(Color));
		T->SetText(FText::FromString(Text));
		Box->AddChildToVerticalBox(T)->SetPadding(FMargin(0.f, PadTop, 0.f, Space1));
		return T;
	};
	AddText(TEXT("DribbleTitle"), TEXT("DRIBBLE LAB"), FontL, AccentGold, 0.f);
	AddText(TEXT("BehaviourHeader"), TEXT("Behaviour   [1-4]"), FontXS, TextMuted, Space2);
	for (int32 b = 0; b < FMath::Min(Behaviours.Num(), MaxDribbleButtons); ++b)
	{
		const bool bTrained = Trained.IsValidIndex(b) && Trained[b];
		BehaviourButtons.Add(MakeDribbleButton(Box, FString::Printf(TEXT("%d   %s   %s"), b + 1, *Behaviours[b], bTrained ? TEXT("trained") : TEXT("untrained")),
			0, b, BehaviourLabels));
	}
	AddText(TEXT("SkinHeader"), TEXT("Humanoid   [H]"), FontXS, TextMuted, Space3);
	for (int32 s = 0; s < FMath::Min(Skins.Num(), MaxDribbleButtons); ++s)
		SkinButtons.Add(MakeDribbleButton(Box, Skins[s], 1, s, SkinLabels));
	DribbleStatsText = AddText(TEXT("DribbleStats"), FString(), FontS, TextPrimary, Space3);
	DribbleStatusText = AddText(TEXT("DribbleStatus"), FString(), FontXS, TextMuted, Space1);
	DribbleStatusText->SetAutoWrapText(true);
	DribbleStatusText->SetWrapTextAt(300.f);
	ShownBehaviour = ShownSkin = -1;
}

UButton* UStreetballHUDWidget::MakeDribbleButton(UVerticalBox* Box, const FString& Label, int32 Kind, int32 Index, TArray<TObjectPtr<UTextBlock>>& OutLabels)
{
	using namespace StreetballUiTheme;
	UButton* B = WidgetTree->ConstructWidget<UButton>(UButton::StaticClass());
	UTextBlock* T = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
	FSlateFontInfo F = T->GetFont();
	F.Size = FontS;
	T->SetFont(F);
	T->SetText(FText::FromString(Label));
	if (UButtonSlot* BS = Cast<UButtonSlot>(B->AddChild(T)))
	{
		BS->SetPadding(FMargin(Space3, Space1));
		BS->SetHorizontalAlignment(HAlign_Left);
	}
	UVerticalBoxSlot* S = Box->AddChildToVerticalBox(B);
	S->SetPadding(FMargin(0.f, 2.f));
	S->SetHorizontalAlignment(HAlign_Fill);
	// AddDynamic needs a literal member function, hence one tiny UFUNCTION per slot
	switch (Kind * MaxDribbleButtons + Index)
	{
	case 0: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnBehaviour0); break;
	case 1: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnBehaviour1); break;
	case 2: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnBehaviour2); break;
	case 3: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnBehaviour3); break;
	case 4: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnBehaviour4); break;
	case 5: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnBehaviour5); break;
	case 6: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnSkin0); break;
	case 7: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnSkin1); break;
	case 8: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnSkin2); break;
	case 9: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnSkin3); break;
	case 10: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnSkin4); break;
	case 11: B->OnClicked.AddDynamic(this, &UStreetballHUDWidget::OnSkin5); break;
	default: break;
	}
	OutLabels.Add(T);
	return B;
}

void UStreetballHUDWidget::StyleDribbleButtons(TArray<TObjectPtr<UButton>>& Buttons, TArray<TObjectPtr<UTextBlock>>& Labels, int32 Active)
{
	static const FLinearColor Idle(0.10f, 0.13f, 0.18f, 0.92f);
	static const FLinearColor ActiveText(0.06f, 0.06f, 0.06f, 1.f);
	for (int32 i = 0; i < Buttons.Num(); ++i)
	{
		const bool bActive = i == Active;
		if (Buttons[i]) Buttons[i]->SetBackgroundColor(bActive ? StreetballUiTheme::AccentGold : Idle);
		if (Labels.IsValidIndex(i) && Labels[i]) Labels[i]->SetColorAndOpacity(FSlateColor(bActive ? ActiveText : StreetballUiTheme::TextPrimary));
	}
}

void UStreetballHUDWidget::RequestDribble(int32 Kind, int32 Index)
{
	OnDribbleUiRequest.Broadcast(Kind, Index);
	// hand the keyboard back to the game, so Space pauses instead of pressing the last clicked button again
	if (FSlateApplication::IsInitialized()) FSlateApplication::Get().SetAllUserFocusToGameViewport();
	TriggerInputPulse();
}

bool UStreetballHUDWidget::IsPointerOverDribblePanel() const
{
	return DribblePanel && DribblePanel->IsHovered();
}

void UStreetballHUDWidget::UpdateDribbleStats(const FStreetballDribbleStats& S)
{
	if (!DribblePanel) return;
	using namespace StreetballUiTheme;
	if (S.Behaviour != ShownBehaviour)
	{
		ShownBehaviour = S.Behaviour;
		StyleDribbleButtons(BehaviourButtons, BehaviourLabels, S.Behaviour);
		if (DribbleStatusText)
		{
			DribbleStatusText->SetText(FText::FromString(S.bTrained
				? TEXT("Trained brain: passed its gate in training.")
				: TEXT("Not trained yet: the right-hand brain is improvising, so expect lost balls and resets.")));
			DribbleStatusText->SetColorAndOpacity(FSlateColor(S.bTrained ? PolicyRef : PolicyBot));
		}
	}
	if (S.Skin != ShownSkin)
	{
		ShownSkin = S.Skin;
		StyleDribbleButtons(SkinButtons, SkinLabels, S.Skin);
	}
	// numbers at 10 Hz (no string building on the other frames)
	const double NowS = FPlatformTime::Seconds();
	if (LastDribbleStatsS >= 0.0 && NowS - LastDribbleStatsS < 0.1) return;
	LastDribbleStatsS = NowS;
	const TCHAR* Hand = S.bScramble ? TEXT("chasing the ball") : S.bRightHand ? TEXT("right") : TEXT("left");
	CachedDribbleStats = FString::Printf(TEXT("Hand  %s\nBounces  %d   (clean %d)\nClean streak  %d\nRun  %.1f s   (best %.1f s)\nResets  %d"),
		Hand, S.Bounces, S.CleanBounces, S.Streak, S.RunS, S.BestRunS, S.Resets);
	if (S.Behaviour == 2) CachedDribbleStats += FString::Printf(TEXT("\nHand switches  %d"), S.HandSwitches);
	if (DribbleStatsText) DribbleStatsText->SetText(FText::FromString(CachedDribbleStats));
}

TSharedRef<SWidget> UStreetballHUDWidget::RebuildWidget()
{
	if (!WidgetTree->RootWidget)
	{
		UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("Canvas"));
		WidgetTree->RootWidget = Canvas;
		Root = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass(), TEXT("Scoreboard"));
		UCanvasPanelSlot* CS = Canvas->AddChildToCanvas(Root);
		CS->SetAnchors(FAnchors(0.f, 0.f));
		CS->SetPosition(FVector2D(StreetballUiTheme::SafeAreaMargin, StreetballUiTheme::SafeAreaMargin));
		CS->SetAutoSize(true);

		auto MakeStyledText = [this](const TCHAR* Name, int32 Size, const FLinearColor& Color) -> UTextBlock*
		{
			UTextBlock* T = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), Name);
			FSlateFontInfo F = T->GetFont();
			F.Size = Size;
			T->SetFont(F);
			T->SetColorAndOpacity(FSlateColor(Color));
			T->SetShadowOffset(FVector2D(1.f, 1.f));
			T->SetShadowColorAndOpacity(StreetballUiTheme::TextShadow);
			return T;
		};

		auto MakeText = [this, &MakeStyledText](const TCHAR* Name, int32 Size, const FLinearColor& Color) -> UTextBlock*
		{
			UTextBlock* T = MakeStyledText(Name, Size, Color);
			UVerticalBoxSlot* S = Root->AddChildToVerticalBox(T);
			S->SetPadding(FMargin(0.f, StreetballUiTheme::Space1 * 0.5f));
			return T;
		};
		UTextBlock* AppTitleText = MakeText(TEXT("AppTitle"), StreetballUiTheme::FontL, FLinearColor::White);
		AppTitleText->SetText(FText::FromString(TEXT("PoBasketball")));
		TierText = MakeText(TEXT("Tier"), StreetballUiTheme::FontL, StreetballUiTheme::AccentGold);
		StateText = MakeText(TEXT("State"), StreetballUiTheme::FontXS, StreetballUiTheme::TextMuted);
		StreakText = MakeText(TEXT("Streak"), StreetballUiTheme::FontS, StreetballUiTheme::TextPrimary);
		DistanceText = MakeText(TEXT("Distance"), StreetballUiTheme::FontS, StreetballUiTheme::TextPrimary);
		MilestoneText = MakeText(TEXT("Milestones"), StreetballUiTheme::FontXS, StreetballUiTheme::PolicyRef);
		ProgressBar = WidgetTree->ConstructWidget<UProgressBar>(UProgressBar::StaticClass(), TEXT("Progress"));
		ProgressBar->SetFillColorAndOpacity(StreetballUiTheme::PolicyCustom);
		UVerticalBoxSlot* PS = Root->AddChildToVerticalBox(ProgressBar);
		PS->SetPadding(FMargin(0.f, StreetballUiTheme::Space1));
		CountdownText = MakeText(TEXT("Countdown"), StreetballUiTheme::FontM, StreetballUiTheme::PolicyBot);

		// Anchor 2: Top-Center mode/camera/seed banner
		ModeBannerText = MakeStyledText(TEXT("ModeBanner"), StreetballUiTheme::FontS, StreetballUiTheme::TextPrimary);
		UCanvasPanelSlot* CenterSlot = Canvas->AddChildToCanvas(ModeBannerText);
		CenterSlot->SetAnchors(FAnchors(0.5f, 0.f));
		CenterSlot->SetAlignment(FVector2D(0.5f, 0.f));
		CenterSlot->SetPosition(FVector2D(0.f, StreetballUiTheme::SafeAreaMargin));
		CenterSlot->SetAutoSize(true);

		// Anchor 3: Top-Right FPS + active policy badge
		PolicyFpsText = MakeStyledText(TEXT("PolicyFps"), StreetballUiTheme::FontS, StreetballUiTheme::PolicyRef);
		PolicyFpsText->SetText(FText::FromString(TEXT("60 FPS  |  ⚙ Settings (Esc)")));
		UCanvasPanelSlot* RightSlot = Canvas->AddChildToCanvas(PolicyFpsText);
		RightSlot->SetAnchors(FAnchors(1.f, 0.f));
		RightSlot->SetAlignment(FVector2D(1.f, 0.f));
		RightSlot->SetPosition(FVector2D(-StreetballUiTheme::SafeAreaMargin, StreetballUiTheme::SafeAreaMargin));
		RightSlot->SetAutoSize(true);

		// Anchor 4: Bottom-Left RL telemetry (reward / NaN-Inf); collapsed by default in Watch/Play
		TelemetryText = MakeStyledText(TEXT("Telemetry"), StreetballUiTheme::FontXS, StreetballUiTheme::TextMuted);
		TelemetryText->SetVisibility(bTelemetryVisible ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
		UCanvasPanelSlot* BLSlot = Canvas->AddChildToCanvas(TelemetryText);
		BLSlot->SetAnchors(FAnchors(0.f, 1.f));
		BLSlot->SetAlignment(FVector2D(0.f, 1.f));
		BLSlot->SetPosition(FVector2D(StreetballUiTheme::SafeAreaMargin, -StreetballUiTheme::SafeAreaMargin));
		BLSlot->SetAutoSize(true);

		// Single compact bottom panel hint bar (Bottom-Center)
		BottomBarText = MakeStyledText(TEXT("BottomBar"), StreetballUiTheme::FontXS, StreetballUiTheme::TextMuted);
		BottomBarText->SetText(FText::FromString(TEXT("F1 Mode  |  F2 Camera  |  F3 Telemetry  |  F4 Policy  |  Space Pause  |  R Reset")));
		UCanvasPanelSlot* BotSlot = Canvas->AddChildToCanvas(BottomBarText);
		BotSlot->SetAnchors(FAnchors(0.5f, 1.f));
		BotSlot->SetAlignment(FVector2D(0.5f, 1.f));
		BotSlot->SetPosition(FVector2D(0.f, -StreetballUiTheme::SafeAreaMargin));
		BotSlot->SetAutoSize(true);

		// Voice subtitle (bottom-centre, above the hint bar)
		SubtitleText = MakeStyledText(TEXT("Subtitle"), StreetballUiTheme::FontL, StreetballUiTheme::AccentGold);
		SubtitleText->SetShadowOffset(FVector2D(1.f, 1.f));
		SubtitleText->SetShadowColorAndOpacity(StreetballUiTheme::SubtitleShadow);
		SubtitleText->SetVisibility(ESlateVisibility::Collapsed);
		UCanvasPanelSlot* SubSlot = Canvas->AddChildToCanvas(SubtitleText);
		SubSlot->SetAnchors(FAnchors(0.5f, 1.f));
		SubSlot->SetAlignment(FVector2D(0.5f, 1.f));
		SubSlot->SetPosition(FVector2D(0.f, -StreetballUiTheme::SafeAreaMargin - 40.f));
		SubSlot->SetAutoSize(true);

		// Anchor 5: UU_AGENT build stamp: compile date as YYMMDD, bottom-right corner.
		UTextBlock* Stamp = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), TEXT("BuildStamp"));
		FSlateFontInfo SF = Stamp->GetFont();
		SF.Size = StreetballUiTheme::FontXS;
		Stamp->SetFont(SF);
		Stamp->SetColorAndOpacity(FSlateColor(StreetballUiTheme::TextStamp));   // readable over the light floor
		Stamp->SetShadowOffset(FVector2D(1.f, 1.f));
		Stamp->SetShadowColorAndOpacity(StreetballUiTheme::TextShadow);
		Stamp->SetText(FText::FromString(FString::Printf(TEXT("v%s"), *BuildStampYYMMDD())));
		StampText = Stamp;
		UCanvasPanelSlot* StampSlot = Canvas->AddChildToCanvas(Stamp);
		StampSlot->SetAnchors(FAnchors(1.f, 1.f));
		StampSlot->SetAlignment(FVector2D(1.f, 1.f));
		StampSlot->SetPosition(FVector2D(-StreetballUiTheme::Space4, -StreetballUiTheme::Space3));
		StampSlot->SetAutoSize(true);
	}
	return Super::RebuildWidget();
}

void UStreetballHUDWidget::NativeTick(const FGeometry& MyGeometry, float InDeltaTime)
{
	Super::NativeTick(MyGeometry, InDeltaTime);
	ApplyLayout(MyGeometry.GetLocalSize());

	// Eased progress bar interpolation
	DisplayedProgress01 = FMath::FInterpTo(DisplayedProgress01, TargetProgress01, InDeltaTime, 10.f);
	if (ProgressBar) ProgressBar->SetPercent(DisplayedProgress01);

	// Tier-up scale pop (cubic ease-out)
	if (TierPopTimer > 0.f)
	{
		TierPopTimer = FMath::Max(0.f, TierPopTimer - InDeltaTime);
		if (TierText)
		{
			const float T = TierPopTimer / 0.35f;
			const float S = 1.f + 0.22f * T * T;
			TierText->SetRenderScale(FVector2D(S, S));
		}
	}

	// Smooth subtitle fade-in / fade-out
	const float TargetSubAlpha = LastSubtitle.IsEmpty() ? 0.f : 1.f;
	SubtitleFadeAlpha = FMath::FInterpTo(SubtitleFadeAlpha, TargetSubAlpha, InDeltaTime, 12.f);
	if (SubtitleText)
	{
		SubtitleText->SetRenderOpacity(SubtitleFadeAlpha);
		if (LastSubtitle.IsEmpty() && SubtitleFadeAlpha < 0.02f)
		{
			SubtitleText->SetVisibility(ESlateVisibility::Collapsed);
		}
	}

	// Screen wipe & input pulse timers
	if (WipeTimer > 0.f) WipeTimer = FMath::Max(0.f, WipeTimer - InDeltaTime);
	if (InputPulseTimer > 0.f) InputPulseTimer = FMath::Max(0.f, InputPulseTimer - InDeltaTime);
}

void UStreetballHUDWidget::TriggerScreenWipe(float DurationS)
{
	WipeDuration = FMath::Max(0.05f, DurationS);
	WipeTimer = WipeDuration;
}

void UStreetballHUDWidget::TriggerInputPulse()
{
	InputPulseTimer = 0.16f;
	bTelemetryDirty = true;
}

void UStreetballHUDWidget::ApplyLayout(const FVector2D& ViewSize)
{
	if (!ModeBannerText || !PolicyFpsText || !TelemetryText || !BottomBarText || !SubtitleText || ViewSize.X <= 1.f) return;
	using namespace StreetballUiTheme;
	const bool bNarrow = ViewSize.X < NarrowWidth || ViewSize.X < ViewSize.Y;
	// The diagnostics corner button (touch devices) sits top-right: keep the policy badge clear of it.
	const UStreetballShowcaseSubsystem* Showcase = UStreetballShowcaseSubsystem::Get(this);
	const float RightInset = SafeAreaMargin + ((Showcase && Showcase->HasTouchButton()) ? 52.f : 0.f);
	auto Place = [](UTextBlock* T, const FVector2D& Anchor, const FVector2D& Align, const FVector2D& Pos)
	{
		if (UCanvasPanelSlot* S = Cast<UCanvasPanelSlot>(T->Slot))
		{
			S->SetAnchors(FAnchors(Anchor.X, Anchor.Y));
			S->SetAlignment(Align);
			S->SetPosition(Pos);
		}
	};
	const float Wrap = bNarrow ? FMath::Max(120.f, ViewSize.X - 2.f * SafeAreaMargin) : 0.f;
	for (UTextBlock* T : { ModeBannerText.Get(), PolicyFpsText.Get(), TelemetryText.Get(), BottomBarText.Get(), SubtitleText.Get() })
	{
		T->SetAutoWrapText(bNarrow);
		T->SetWrapTextAt(Wrap);
	}
	if (!bNarrow)
	{
		if (LayoutMode == 0 && FMath::IsNearlyEqual(LayoutWidth, ViewSize.X)) return;
		Place(ModeBannerText, FVector2D(0.5f, 0.f), FVector2D(0.5f, 0.f), FVector2D(0.f, SafeAreaMargin));
		Place(PolicyFpsText, FVector2D(1.f, 0.f), FVector2D(1.f, 0.f), FVector2D(-RightInset, SafeAreaMargin));
		Place(TelemetryText, FVector2D(0.f, 1.f), FVector2D(0.f, 1.f), FVector2D(SafeAreaMargin, -SafeAreaMargin));
		Place(BottomBarText, FVector2D(0.5f, 1.f), FVector2D(0.5f, 1.f), FVector2D(0.f, -SafeAreaMargin));
		Place(SubtitleText, FVector2D(0.5f, 1.f), FVector2D(0.5f, 1.f), FVector2D(0.f, -SafeAreaMargin - 40.f));
		LayoutMode = 0;
		LayoutWidth = ViewSize.X;
		return;
	}
	// Narrow: bottom-up stack above the version stamp row (stamp: bottom-right, ~20 px tall at Space3 from the edge).
	float Y = -(Space3 + 22.f + Space2);
	auto Stack = [&Place, &Y](UTextBlock* T)
	{
		if (T->GetVisibility() == ESlateVisibility::Collapsed) return;
		Place(T, FVector2D(0.f, 1.f), FVector2D(0.f, 1.f), FVector2D(SafeAreaMargin, Y));
		Y -= T->GetDesiredSize().Y + Space1;
	};
	Stack(BottomBarText);
	Stack(TelemetryText);
	Stack(PolicyFpsText);
	Stack(ModeBannerText);
	Y -= Space3;
	Stack(SubtitleText);
	LayoutMode = 1;
	LayoutWidth = ViewSize.X;
}

FString UStreetballHUDWidget::BuildStampYYMMDD()
{
	// One version stamp: UTC yyMMdd of the HEAD commit, computed once in StreetballGym.Build.cs (web/build.py uses the same rule).
	return TEXT(STREETBALL_BUILD_VERSION);
}

void UStreetballHUDWidget::UpdateFromProgress(const FStreetballProgress& P, EStreetballState State)
{
	CachedTier = P.TierName;
	CachedStreak = FString::Printf(TEXT("Clean dribbles: %d   Saves: %d   Shots: %d/%d"), P.CleanStreak, P.Saves, P.ShotsMade, P.ShotsTaken);
	CachedDistance = FString::Printf(TEXT("Distance: %.1f m   Balance: %.0f s   Waypoints: %d"), P.TotalDistance, P.BalanceTime, P.Waypoints);
	FString M;
	for (int32 i = 0; i < 5; ++i) M += FString::Printf(TEXT("[%s] T%d  "), P.Mastered[i] ? TEXT("x") : TEXT(" "), i + 1);
	ProgressPercent = 100.f * P.Progress01;
	M += FString::Printf(TEXT("  %.0f%% of tier %d"), ProgressPercent, P.ActiveTier);
	CachedMilestone = M;
	bLoose = P.bLoose;
	CountdownFrac = P.CountdownFrac;

	if (TierText)
	{
		TierText->SetText(FText::FromString(CachedTier));
		if (LastTierNum >= 0 && P.ActiveTier != LastTierNum) TierPopTimer = 0.35f;
		LastTierNum = P.ActiveTier;
	}
	if (StateText) StateText->SetText(FText::FromString(UStreetballDirector::StateName(State)));
	if (StreakText) StreakText->SetText(FText::FromString(CachedStreak));
	if (DistanceText) DistanceText->SetText(FText::FromString(CachedDistance));
	if (MilestoneText) MilestoneText->SetText(FText::FromString(CachedMilestone));
	TargetProgress01 = P.Progress01;
	if (ProgressBar && FMath::IsNearlyZero(DisplayedProgress01) && P.Progress01 > 0.f)
	{
		DisplayedProgress01 = P.Progress01;
		ProgressBar->SetPercent(DisplayedProgress01);
	}
	if (CountdownText)
	{
		CountdownText->SetText(FText::FromString(bLoose ? FString::Printf(TEXT("LOOSE BALL  %.1f s"), 3.f * CountdownFrac) : FString()));
		CountdownText->SetVisibility(bLoose ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
	}
}

FString UStreetballHUDWidget::GetTierText() const { return CachedTier; }
FString UStreetballHUDWidget::GetStreakText() const { return CachedStreak; }
FString UStreetballHUDWidget::GetDistanceText() const { return CachedDistance; }
FString UStreetballHUDWidget::GetMilestoneText() const { return CachedMilestone; }
float UStreetballHUDWidget::GetProgressPercent() const { return ProgressPercent; }
FString UStreetballHUDWidget::GetBuildStampText() const { return StampText ? StampText->GetText().ToString() : FString(); }

void UStreetballHUDWidget::SetTelemetryVisible(bool bVisible)
{
	bTelemetryVisible = bVisible;
	bTelemetryDirty = true;
	if (TelemetryText)
	{
		TelemetryText->SetVisibility(bVisible ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
	}
}

void UStreetballHUDWidget::UpdateTelemetry(const FString& ModeLabel, const FString& CameraLabel, const FString& PolicyLabel,
                                           int32 Seed, float EpisodeReward, int32 NanInfCount, float Fps, bool bPaused, bool bFallbackPolicy,
                                           float Exertion01, float PowerW, float TimeScale)
{
	const double NowS = FPlatformTime::Seconds();
	const bool bStateChanged = bTelemetryDirty
		|| ModeLabel != LastModeLabel
		|| CameraLabel != LastCameraLabel
		|| PolicyLabel != LastPolicyLabel
		|| bPaused != bLastPaused
		|| bFallbackPolicy != bLastFallbackPolicy
		|| !FMath::IsNearlyEqual(TimeScale, LastTimeScale, 0.01f);

	// Throttle steady-state numeric refreshes to 10 Hz; apply immediately on state transitions or active pulse.
	const bool bDue = LastTelemetryUpdateS < 0.0 || (NowS - LastTelemetryUpdateS) >= 0.1;
	if (!bStateChanged && !bDue && InputPulseTimer <= 0.f)
	{
		return;
	}

	if (bStateChanged || bDue)
	{
		LastTelemetryUpdateS = NowS;
		bTelemetryDirty = false;
		LastModeLabel = ModeLabel;
		LastCameraLabel = CameraLabel;
		LastPolicyLabel = PolicyLabel;
		bLastPaused = bPaused;
		bLastFallbackPolicy = bFallbackPolicy;
		LastTimeScale = TimeScale;

		if (ModeBannerText)
		{
			const FString ScaleStr = FMath::IsNearlyEqual(TimeScale, 1.f, 0.02f) ? FString() : FString::Printf(TEXT("  |  %.2fx"), TimeScale);
			ModeBannerText->SetText(FText::FromString(FString::Printf(
				TEXT("%s  |  Cam: %s  |  Seed: %d%s%s"), *ModeLabel, *CameraLabel, Seed, *ScaleStr, bPaused ? TEXT("  |  PAUSED") : TEXT(""))));
		}
		if (PolicyFpsText)
		{
			PolicyFpsText->SetText(FText::FromString(FString::Printf(TEXT("%.0f FPS  |  Policy: %s"), Fps, *PolicyLabel)));
		}
		if (TelemetryText)
		{
			TelemetryText->SetVisibility(bTelemetryVisible ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
			if (bTelemetryVisible)
			{
				TelemetryText->SetColorAndOpacity(FSlateColor(NanInfCount > 0 ? StreetballUiTheme::PolicyBot : StreetballUiTheme::TextMuted));
				TelemetryText->SetText(FText::FromString(FString::Printf(
					TEXT("Reward: %.2f  |  Power: %.0f W (Exertion %.0f%%)  |  NaN/Inf: %d"),
					EpisodeReward, PowerW, Exertion01 * 100.f, NanInfCount)));
			}
		}
	}

	if (PolicyFpsText)
	{
		const FLinearColor BaseCol = bFallbackPolicy ? StreetballUiTheme::PolicyBot : StreetballUiTheme::PolicyRef;
		const FLinearColor Col = (InputPulseTimer > 0.f)
			? FMath::Lerp(BaseCol, StreetballUiTheme::AccentIndigo, InputPulseTimer / 0.16f)
			: BaseCol;
		PolicyFpsText->SetColorAndOpacity(FSlateColor(Col));
	}
}

void UStreetballHUDWidget::SetModeHint(const FString& HintText)
{
	if (!BottomBarText || HintText == LastModeHint) return;
	LastModeHint = HintText;
	BottomBarText->SetText(FText::FromString(HintText));
}

int32 UStreetballHUDWidget::NativePaint(const FPaintArgs& Args, const FGeometry& Geo, const FSlateRect& Cull,
                                        FSlateWindowElementList& Out, int32 LayerId, const FWidgetStyle& Style, bool bParentEnabled) const
{
	LayerId = Super::NativePaint(Args, Geo, Cull, Out, LayerId, Style, bParentEnabled);
	const FVector2D Size = Geo.GetLocalSize();
	if (WipeTimer > 0.f && WipeDuration > 0.f)
	{
		const float U = FMath::Clamp(WipeTimer / WipeDuration, 0.f, 1.f);
		const float Alpha = 0.55f * U * U;
		const float BarW = Size.X * (1.f - U);
		FLinearColor WipeColor = StreetballUiTheme::WipeOverlay;
		WipeColor.A = Alpha;
		FSlateDrawElement::MakeBox(
			Out, LayerId + 3,
			Geo.ToPaintGeometry(FVector2D(Size.X - BarW, Size.Y), FSlateLayoutTransform(FVector2D(BarW, 0.f))),
			FCoreStyle::Get().GetBrush("WhiteBrush"), ESlateDrawEffect::None, WipeColor);
	}
	if (!bLoose) return LayerId + 3;
	// Countdown ring: bottom-left corner, sweeps down as the 3 s grace period runs out.
	const FVector2D C(90.f, Size.Y - 90.f);
	const float R = 42.f;
	const int32 Segs = 48;
	TArray<FVector2D> Back, Arc;
	for (int32 i = 0; i <= Segs; ++i)
	{
		const float A = -PI / 2 + 2 * PI * i / Segs;
		Back.Add(C + FVector2D(FMath::Cos(A), FMath::Sin(A)) * R);
	}
	const int32 N = FMath::Clamp((int32)FMath::RoundToInt(Segs * CountdownFrac), 0, Segs);
	for (int32 i = 0; i <= N; ++i)
	{
		const float A = -PI / 2 + 2 * PI * i / Segs;
		Arc.Add(C + FVector2D(FMath::Cos(A), FMath::Sin(A)) * R);
	}
	FSlateDrawElement::MakeLines(Out, LayerId + 1, Geo.ToPaintGeometry(), Back, ESlateDrawEffect::None, StreetballUiTheme::CountdownTrack, true, 4.f);
	if (Arc.Num() > 1)
	{
		FSlateDrawElement::MakeLines(Out, LayerId + 2, Geo.ToPaintGeometry(), Arc, ESlateDrawEffect::None, StreetballUiTheme::CountdownArc, true, 6.f);
	}
	return LayerId + 2;
}

void UStreetballHUDWidget::SetSubtitle(const FString& Text)
{
	if (!SubtitleText) return;
	if (Text.IsEmpty())
	{
		LastSubtitle.Reset();
		return;
	}
	if (Text == LastSubtitle) return;
	LastSubtitle = Text;
	SubtitleText->SetText(FText::FromString(FString::Printf(TEXT("Grandma: \"%s\""), *Text)));
	SubtitleText->SetVisibility(ESlateVisibility::HitTestInvisible);
}

FString UStreetballHUDWidget::GetSubtitle() const
{
	return LastSubtitle;
}
