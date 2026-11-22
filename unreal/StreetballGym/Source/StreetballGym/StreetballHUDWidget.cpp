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
			T->SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.8f));
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

		// Anchor 4: Bottom-Left RL telemetry (reward / NaN-Inf)
		TelemetryText = MakeStyledText(TEXT("Telemetry"), StreetballUiTheme::FontXS, StreetballUiTheme::TextMuted);
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
		SubtitleText->SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.85f));
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
		Stamp->SetColorAndOpacity(FSlateColor(FLinearColor(1.f, 1.f, 1.f, 0.9f)));   // readable over the light floor
		Stamp->SetShadowOffset(FVector2D(1.f, 1.f));
		Stamp->SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.8f));
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

	if (TierText) TierText->SetText(FText::FromString(CachedTier));
	if (StateText) StateText->SetText(FText::FromString(UStreetballDirector::StateName(State)));
	if (StreakText) StreakText->SetText(FText::FromString(CachedStreak));
	if (DistanceText) DistanceText->SetText(FText::FromString(CachedDistance));
	if (MilestoneText) MilestoneText->SetText(FText::FromString(CachedMilestone));
	if (ProgressBar) ProgressBar->SetPercent(P.Progress01);
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
	if (TelemetryText)
	{
		TelemetryText->SetVisibility(bVisible ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
	}
}

void UStreetballHUDWidget::UpdateTelemetry(const FString& ModeLabel, const FString& CameraLabel, const FString& PolicyLabel,
                                           int32 Seed, float EpisodeReward, int32 NanInfCount, float Fps, bool bPaused, bool bFallbackPolicy,
                                           float Exertion01, float PowerW, float TimeScale)
{
	if (ModeBannerText)
	{
		const FString ScaleStr = FMath::IsNearlyEqual(TimeScale, 1.f, 0.02f) ? FString() : FString::Printf(TEXT("  |  %.2fx"), TimeScale);
		ModeBannerText->SetText(FText::FromString(FString::Printf(
			TEXT("%s  |  Cam: %s  |  Seed: %d%s%s"), *ModeLabel, *CameraLabel, Seed, *ScaleStr, bPaused ? TEXT("  |  PAUSED") : TEXT(""))));
	}
	if (PolicyFpsText)
	{
		PolicyFpsText->SetColorAndOpacity(FSlateColor(bFallbackPolicy ? StreetballUiTheme::PolicyBot : StreetballUiTheme::PolicyRef));
		PolicyFpsText->SetText(FText::FromString(FString::Printf(TEXT("%.0f FPS  |  Policy: %s"), Fps, *PolicyLabel)));
	}
	if (TelemetryText)
	{
		TelemetryText->SetColorAndOpacity(FSlateColor(NanInfCount > 0 ? StreetballUiTheme::PolicyBot : StreetballUiTheme::TextMuted));
		TelemetryText->SetText(FText::FromString(FString::Printf(
			TEXT("Reward: %.2f  |  Power: %.0f W (Exertion %.0f%%)  |  NaN/Inf: %d"),
			EpisodeReward, PowerW, Exertion01 * 100.f, NanInfCount)));
		TelemetryText->SetVisibility(bTelemetryVisible ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
	}
}

void UStreetballHUDWidget::SetModeHint(const FString& HintText)
{
	if (BottomBarText) BottomBarText->SetText(FText::FromString(HintText));
}

int32 UStreetballHUDWidget::NativePaint(const FPaintArgs& Args, const FGeometry& Geo, const FSlateRect& Cull,
                                        FSlateWindowElementList& Out, int32 LayerId, const FWidgetStyle& Style, bool bParentEnabled) const
{
	LayerId = Super::NativePaint(Args, Geo, Cull, Out, LayerId, Style, bParentEnabled);
	if (!bLoose) return LayerId;
	// Countdown ring: bottom-left corner, sweeps down as the 3 s grace period runs out.
	const FVector2D Size = Geo.GetLocalSize();
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
	FSlateDrawElement::MakeLines(Out, LayerId + 1, Geo.ToPaintGeometry(), Back, ESlateDrawEffect::None, FLinearColor(1, 1, 1, 0.25f), true, 4.f);
	if (Arc.Num() > 1)
	{
		FSlateDrawElement::MakeLines(Out, LayerId + 2, Geo.ToPaintGeometry(), Arc, ESlateDrawEffect::None, FLinearColor(1.f, 0.45f, 0.25f, 0.95f), true, 6.f);
	}
	return LayerId + 2;
}

void UStreetballHUDWidget::SetSubtitle(const FString& Text)
{
	if (!SubtitleText) return;
	if (Text.IsEmpty())
	{
		if (!LastSubtitle.IsEmpty()) SubtitleText->SetVisibility(ESlateVisibility::Collapsed);
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
