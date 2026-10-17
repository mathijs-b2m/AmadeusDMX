// The show: the stage edge to edge, glass panels floating over it, the director in the inspector.
namespace AmadeusDMX;

public sealed class ShowView(AppModel model)
{
    /// The stage's camera, haze, LED wall… (Swift's StageController, a @StateObject of the window): kept while
    /// the app runs, like the page itself (MainWindow builds it once).
    public StageSettings Stage { get; } = new();

    public FrameworkElement Build()
    {
        var feed = model.Feed;

        // the stage, or the Perform board: no 3D view at all in Perform Only (nothing is drawn 60 times a second)
        bool? renders = null;
        var back = new ContentControl
        {
            HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
        }.Bind(model, nameof(AppModel.Mode), c =>
        {
            if (renders == model.Mode.Renders3D()) return;  // the same kind: keep it (the stage is costly to make)
            renders = model.Mode.Renders3D();
            c.Content = renders == true ? StageHost.Create(model, Stage) : new PerformBoard(model).Build();
        });

        var noSet = UI.Unavailable("square.stack.3d.up.slash", "No Set", "Create a set to see the rig here.");
        void NoSet(FrameworkElement e) => e.Visible(model.Mode.Renders3D() && model.StageInput() is null);
        noSet.Bind(model, [nameof(AppModel.Mode), nameof(AppModel.SelectedSet), nameof(AppModel.SelectedRig), nameof(AppModel.ConfigVersion)], NoSet)
             .Bind(feed, [nameof(LiveFeed.Hello), nameof(LiveFeed.State)], NoSet);

        // the cards: at the top the track, the night and the decks; at the bottom the timeline and the stage's controls
        var night = new NightCard(model).Build().Align(VerticalAlignment.Top)
            .Bind(feed, [nameof(LiveFeed.Arc), nameof(LiveFeed.State)], n => n.Visible(feed.Arc is not null && feed.State == FeedState.Connected));
        var decks = new DecksCard(model).Build().Align(VerticalAlignment.Top);
        void Decks(FrameworkElement e) => e.Visible(feed.Decks.Count > 0 && (model.EngineRunning || model.ShowState.Kind == ShowStateKind.Attached));
        decks.Bind(feed, nameof(LiveFeed.Decks), Decks).Bind(model, [nameof(AppModel.EngineRunning), nameof(AppModel.ShowState)], Decks);
        var top = UI.HStack(12,
            new NowPlayingCard(model).Build().Align(VerticalAlignment.Top),
            UI.Spacer(12),
            night,
            decks);

        Hello? shown = null;
        var timeline = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false, VerticalAlignment = VerticalAlignment.Bottom }
            .Bind(feed, [nameof(LiveFeed.Hello), nameof(LiveFeed.State)], c =>
            {
                var h = feed.State == FeedState.Connected ? feed.Hello : null;
                if (ReferenceEquals(h, shown) && (c.Content is not null) == (h is not null)) return;
                shown = h;
                c.Content = h is null ? null : new TimelineCard(model, h).Build();
            });
        var controls = new StageControls(Stage, model).Build().Align(VerticalAlignment.Bottom)
            .Bind(model, nameof(AppModel.Mode), e => e.Visible(model.Mode.Renders3D()));
        var bottom = UI.HStack(12, timeline.Grow(), controls);

        var cards = UI.VStack(12, top, UI.Spacer(), bottom).Padding(16);
        var stage = UI.ZStack(back, noSet, cards);

        // the director, in the inspector at the right (Ctrl+Alt+I, the toolbar's button)
        var inspector = new Border
        {
            Child = new DirectorInspector(model).Build(),
            Background = Theme.Brush("LayerFillColorDefaultBrush"),
            BorderBrush = Theme.Brush("DividerStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(1, 0, 0, 0),
        };
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var column = new ColumnDefinition { Width = new GridLength(320) };
        root.ColumnDefinitions.Add(column);
        Grid.SetColumn(inspector, 1);
        root.Children.Add(stage);
        root.Children.Add(inspector);
        return root.Bind(model, nameof(AppModel.ShowInspector), _ =>
        {
            column.Width = new GridLength(model.ShowInspector ? 320 : 0);
            inspector.Visible(model.ShowInspector);
        });
    }
}
