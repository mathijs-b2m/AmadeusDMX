// Undo and redo for the rig editor: the part of Foundation's UndoManager the editor uses (the Mac gets it from the
// window; here the editor view owns one). Registrations made while undoing become the redo; made while redoing,
// the undo again; any other registration starts a new history (the redo is forgotten). Without an open group each
// registration is a step of its own (the editor registers one per change); Begin/EndUndoGrouping put several in one.
//
// No WinUI in this file: it is compiled into the kit's tests too.
using AmadeusKit;

namespace AmadeusDMX;

public sealed class UndoManager : Observable
{
    sealed class Group
    {
        public readonly List<Action> Actions = [];
        public string Name = "";
    }

    readonly List<Group> _undo = [], _redo = [];
    Group? _open;        // an explicit group (Begin/EndUndoGrouping)
    int _level;
    Group? _collect;     // what an undo or redo registers (it becomes the other side's step)
    bool _undoing;

    /// Foundation's flag; kept for the ported code (every registration outside a group is its own step here).
    public bool GroupsByEvent { get; set; } = true;

    public bool CanUndo => _undo.Count > 0 || _open is { Actions.Count: > 0 };
    public bool CanRedo => _redo.Count > 0;
    public string UndoActionName => _open is { Actions.Count: > 0 } o ? o.Name : _undo.Count > 0 ? _undo[^1].Name : "";
    public string RedoActionName => _redo.Count > 0 ? _redo[^1].Name : "";

    /// "Undo Move Truss" / "Undo".
    public string UndoMenuTitle => UndoActionName.Length > 0 ? $"Undo {UndoActionName}" : "Undo";
    public string RedoMenuTitle => RedoActionName.Length > 0 ? $"Redo {RedoActionName}" : "Redo";

    public void BeginUndoGrouping()
    {
        if (_level++ == 0) _open = new Group();
    }

    public void EndUndoGrouping()
    {
        if (_level == 0) return;
        if (--_level == 0) CloseGroup();
    }

    void CloseGroup()
    {
        var g = _open;
        _open = null;
        _level = 0;
        if (g is { Actions.Count: > 0 }) _undo.Add(g);
        Tell();
    }

    public void RegisterUndo(Action undo)
    {
        if (_collect is { } c) { c.Actions.Add(undo); return; }
        _redo.Clear();  // a new change: what was undone can't be redone any more
        if (_open is { } g) g.Actions.Add(undo);
        else _undo.Add(new Group { Actions = { undo } });
        Tell();
    }

    /// Names the step just registered (the menu shows "Undo NAME").
    public void SetActionName(string name)
    {
        if (_collect is { } c) c.Name = name;
        else if (_open is { } g) g.Name = name;
        else if (_undo.Count > 0) _undo[^1].Name = name;
        Tell();
    }

    public void Undo()
    {
        if (_collect is not null) return;
        if (_level > 0) CloseGroup();  // an open group is closed first, then undone (as Foundation does)
        if (_undo.Count == 0) return;
        var g = _undo[^1];
        _undo.RemoveAt(_undo.Count - 1);
        Run(g, undoing: true);
    }

    public void Redo()
    {
        if (_collect is not null || _redo.Count == 0) return;
        var g = _redo[^1];
        _redo.RemoveAt(_redo.Count - 1);
        Run(g, undoing: false);
    }

    void Run(Group g, bool undoing)
    {
        _collect = new Group { Name = g.Name };
        _undoing = undoing;
        try
        {
            for (var i = g.Actions.Count - 1; i >= 0; i--) g.Actions[i]();
        }
        finally
        {
            var back = _collect;
            _collect = null;
            // registered while the step ran last-first: run last-first again, they go first-first
            if (back.Actions.Count > 0) (_undoing ? _redo : _undo).Add(back);
            Tell();
        }
    }

    public void RemoveAllActions()
    {
        _undo.Clear();
        _redo.Clear();
        _open = null;
        _level = 0;
        Tell();
    }

    void Tell() => Changed(nameof(CanUndo), nameof(CanRedo), nameof(UndoActionName), nameof(RedoActionName),
                           nameof(UndoMenuTitle), nameof(RedoMenuTitle));
}
