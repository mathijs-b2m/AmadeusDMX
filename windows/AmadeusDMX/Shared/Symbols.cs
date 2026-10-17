// SF Symbols (the Mac app's icons) → Segoe Fluent Icons glyphs (Windows 11; Segoe MDL2 Assets on Windows 10 has
// the same code points). Views keep the Mac's symbol names, so a ported view reads like its Swift; a name that
// isn't here yet shows a neutral glyph (add it here). A one-character string is taken as a glyph itself.
namespace AmadeusDMX;

public static class Symbols
{
    public const string Unknown = "";

    static readonly Dictionary<string, string> Map = new()
    {
        // pages and the show's state
        ["sparkles.tv"] = "", ["square.split.bottomrightquarter"] = "", ["light.overhead.right"] = "",
        ["light.overhead.right.fill"] = "", ["terminal"] = "", ["gearshape"] = "",
        ["stop.circle"] = "", ["hourglass"] = "", ["dot.radiowaves.left.and.right"] = "",
        ["dot.radiowaves.left.and.right.slash"] = "", ["antenna.radiowaves.left.and.right"] = "",
        ["waveform"] = "", ["waveform.path"] = "", ["play.circle"] = "", ["eye"] = "", ["eye.slash"] = "",
        ["exclamationmark.triangle"] = "", ["exclamationmark.triangle.fill"] = "", ["exclamationmark.octagon.fill"] = "",
        ["exclamationmark.shield"] = "", ["xmark.octagon.fill"] = "",
        // modes and the toolbar
        ["cube.transparent"] = "", ["light.beacon.max"] = "", ["square.stack.3d.up"] = "",
        ["square.stack.3d.up.slash"] = "", ["list.bullet.rectangle"] = "", ["sparkles"] = "",
        ["play.fill"] = "", ["stop.fill"] = "", ["pause.fill"] = "", ["sidebar.trailing"] = "",
        ["laptopcomputer"] = "", ["laptopcomputer.and.arrow.down"] = "", ["music.note"] = "",
        ["music.note.list"] = "", ["music.quarternote.3"] = "", ["music.mic"] = "",
        ["sun.max"] = "", ["sun.max.trianglebadge.exclamationmark.fill"] = "",
        ["cable.connector"] = "", ["cable.connector.slash"] = "", ["shippingbox"] = "", ["shippingbox.fill"] = "",
        ["link.circle.fill"] = "",
        // common actions
        ["plus"] = "", ["minus"] = "", ["minus.circle"] = "", ["minus.circle.fill"] = "",
        ["checkmark"] = "", ["checkmark.circle"] = "", ["checkmark.circle.fill"] = "", ["checkmark.seal.fill"] = "",
        ["checklist"] = "", ["xmark.circle.fill"] = "", ["trash"] = "", ["pencil"] = "",
        ["folder"] = "", ["printer"] = "", ["magnifyingglass"] = "", ["key"] = "", ["key.fill"] = "",
        ["clock"] = "", ["info.circle"] = "", ["doc.on.doc"] = "", ["doc.text"] = "",
        ["plus.square.on.square"] = "", ["arrow.counterclockwise"] = "", ["arrow.triangle.2.circlepath"] = "",
        ["arrow.down.circle"] = "", ["arrow.up.circle"] = "", ["arrow.down.to.line"] = "", ["arrow.up.to.line"] = "",
        ["arrow.right"] = "", ["arrow.up.right"] = "", ["arrow.down.right"] = "", ["arrow.left.and.right"] = "",
        ["arrow.up.and.down.and.arrow.left.and.right"] = "", ["rotate.right"] = "",
        ["chevron.down"] = "", ["chevron.left"] = "", ["chevron.right"] = "",
        ["pin.fill"] = "", ["cursorarrow"] = "", ["hand.draw"] = "", ["hand.raised.fill"] = "",
        ["wand.and.stars"] = "", ["slider.horizontal.3"] = "", ["slider.vertical.3"] = "",
        ["line.3.horizontal"] = "", ["list.bullet"] = "", ["list.number"] = "", ["textformat.size"] = "",
        ["puzzlepiece.extension"] = "", ["puzzlepiece.extension.fill"] = "",
        // the show
        ["bolt.fill"] = "", ["lightbulb.fill"] = "", ["lightbulb.max"] = "", ["light.strip.2"] = "",
        ["light.panel"] = "", ["light.recessed"] = "", ["cloud.fog"] = "", ["moon.stars"] = "",
        ["moon.zzz"] = "", ["person.2"] = "", ["person.3"] = "", ["person.3.fill"] = "",
        ["person.3.sequence"] = "", ["figure.dance"] = "", ["figure.run"] = "", ["figure.walk.motion"] = "",
        ["film.stack"] = "", ["chart.bar"] = "", ["building.2"] = "", ["building.columns"] = "",
        ["square.grid.2x2"] = "", ["square.grid.3x3"] = "", ["squareshape.split.3x3"] = "",
        ["square.3.layers.3d.down.right"] = "", ["rectangle.stack"] = "", ["rectangle.dashed"] = "",
        ["square.dashed"] = "", ["rectangle.portrait"] = "", ["rectangle.slash"] = "",
        ["circle.dashed"] = "", ["circle.dotted"] = "", ["circle.fill"] = "", ["largecircle.fill.circle"] = "",
        ["circle.hexagongrid"] = "", ["line.diagonal"] = "", ["thermometer.medium"] = "", ["id.1"] = "",
        ["id.2"] = "",
        // the Set page, the wizard
        ["rays"] = "", ["bolt"] = "", ["lightbulb"] = "", ["circle"] = "",
    };

    public static string Glyph(string symbol) =>
        symbol.Length == 1 ? symbol : Map.TryGetValue(symbol, out var g) ? g : Unknown;
}
