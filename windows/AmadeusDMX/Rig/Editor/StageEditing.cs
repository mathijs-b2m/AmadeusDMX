// The rig editor gets first go at clicks, drags and keys on the stage: the port of Swift's `StageEditing` protocol
// (mac/Sources/AmadeusDMX/Render/StageView.swift). The stage view (Render.StageView, or the editor's placeholder)
// turns a pointer position into a ray (the renderer's `ray(at:in:)`) and hands it here; when `Pick` grabs something,
// drags move it instead of the camera.
//
// No WinUI in this file: it is compiled into the kit's tests too (the editor's model is tested on a Mac).
using System.Numerics;

namespace AmadeusDMX;

/// The keys the editor knows by their position (Swift's NSEvent keyCodes 51, 117, 123–126, 53); the rest by their
/// characters.
public enum EditorKeyCode { Other, Backspace, Delete, Left, Right, Up, Down, Escape }

/// A key pressed over the stage (Swift: NSEvent). `Characters`: what it types, without modifiers ("r", "a", "t").
/// On Windows Ctrl is the Mac's ⌘, Alt its ⌥.
public readonly record struct EditorKey(EditorKeyCode Code, string Characters = "", bool Shift = false, bool Alt = false,
                                        bool Control = false)
{
    /// A character key (R, T, A…), lower case.
    public static EditorKey Char(string c, bool shift = false, bool alt = false, bool control = false) =>
        new(EditorKeyCode.Other, c.ToLowerInvariant(), shift, alt, control);
}

/// The rig editor, as the stage view sees it. Rays are in the stage's metres (x across, y towards the audience,
/// z up), like the renderer's.
public interface IStageEditing
{
    /// A click: true if it grabbed something (then drags move it instead of the camera). `extend`: Shift held.
    bool Pick(Vector3 origin, Vector3 dir, bool extend);
    /// The pointer moved with the button down after a Pick that grabbed. `free`: Alt held (no snapping).
    void Drag(Vector3 origin, Vector3 dir, bool free);
    void EndDrag();
    /// A click on nothing (a Pick that grabbed nothing, single click).
    void ClickedEmpty();
    /// A key on the stage: true if the editor used it.
    bool Key(EditorKey e);
    /// Something dragged in from elsewhere (text, e.g. fixture ids from the inspector) is over / dropped on the stage.
    void DropHover(Vector3 origin, Vector3 dir) { }
    bool Drop(string payload, Vector3 origin, Vector3 dir) => false;
    void DropEnded() { }
    /// The pointer moved over the stage (no button down).
    void Hover(Vector3 origin, Vector3 dir) { }
}
