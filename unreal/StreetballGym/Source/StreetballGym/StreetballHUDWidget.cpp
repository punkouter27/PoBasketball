#include "StreetballHUDWidget.h"
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
		CS->SetPosition(FVector2D(24.f, 24.f));
		CS->SetAutoSize(true);

		auto MakeText = [this](const TCHAR* Name, int32 Size, const FLinearColor& Color) -> UTextBlock*
		{
			UTextBlock* T = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), Name);
			FSlateFontInfo F = T->GetFont();
			F.Size = Size;
			T->SetFont(F);
			T->SetColorAndOpacity(FSlateColor(Color));
			T->SetShadowOffset(FVector2D(1.f, 1.f));
			T->SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.8f));
			UVerticalBoxSlot* S = Root->AddChildToVerticalBox(T);
			S->SetPadding(FMargin(0.f, 2.f));
			return T;
		};
		TierText = MakeText(TEXT("Tier"), 22, FLinearColor(1.f, 0.85f, 0.3f));
		StateText = MakeText(TEXT("State"), 14, FLinearColor(0.8f, 0.8f, 0.8f));
		StreakText = MakeText(TEXT("Streak"), 16, FLinearColor::White);
		DistanceText = MakeText(TEXT("Distance"), 16, FLinearColor::White);
		MilestoneText = MakeText(TEXT("Milestones"), 14, FLinearColor(0.7f, 1.f, 0.7f));
		ProgressBar = WidgetTree->ConstructWidget<UProgressBar>(UProgressBar::StaticClass(), TEXT("Progress"));
		ProgressBar->SetFillColorAndOpacity(FLinearColor(0.3f, 0.8f, 1.f));
		UVerticalBoxSlot* PS = Root->AddChildToVerticalBox(ProgressBar);
		PS->SetPadding(FMargin(0.f, 4.f));
		CountdownText = MakeText(TEXT("Countdown"), 18, FLinearColor(1.f, 0.4f, 0.3f));

		// UU_AGENT build stamp: compile date as YYMMDD, bottom-right corner.
		UTextBlock* Stamp = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), TEXT("BuildStamp"));
		FSlateFontInfo SF = Stamp->GetFont();
		SF.Size = 14;
		Stamp->SetFont(SF);
		Stamp->SetColorAndOpacity(FSlateColor(FLinearColor(1.f, 1.f, 1.f, 0.9f)));   // readable over the light floor
		Stamp->SetShadowOffset(FVector2D(1.f, 1.f));
		Stamp->SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.8f));
		Stamp->SetText(FText::FromString(FString::Printf(TEXT("build %s"), *BuildStampYYMMDD())));
		StampText = Stamp;
		UCanvasPanelSlot* StampSlot = Canvas->AddChildToCanvas(Stamp);
		StampSlot->SetAnchors(FAnchors(1.f, 1.f));
		StampSlot->SetAlignment(FVector2D(1.f, 1.f));
		StampSlot->SetPosition(FVector2D(-16.f, -12.f));
		StampSlot->SetAutoSize(true);
	}
	return Super::RebuildWidget();
}

FString UStreetballHUDWidget::BuildStampYYMMDD()
{
	// __DATE__ is "Mmm dd yyyy" (day space-padded), e.g. "Nov  6 2026" -> "261106"
	static const TCHAR* Months[] = { TEXT("Jan"), TEXT("Feb"), TEXT("Mar"), TEXT("Apr"), TEXT("May"), TEXT("Jun"),
	                                 TEXT("Jul"), TEXT("Aug"), TEXT("Sep"), TEXT("Oct"), TEXT("Nov"), TEXT("Dec") };
	const FString D = TEXT(__DATE__);
	int32 Month = 0;
	for (int32 i = 0; i < 12; ++i) if (D.StartsWith(Months[i])) { Month = i + 1; break; }
	const int32 Day = FCString::Atoi(*D.Mid(4, 2).TrimStart());
	const int32 Year = FCString::Atoi(*D.Mid(7, 4)) % 100;
	return FString::Printf(TEXT("%02d%02d%02d"), Year, Month, Day);
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
