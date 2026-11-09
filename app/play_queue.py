"""The play queue: its items, which one plays, and the order from before shuffling (M9).

The window plays from it and the library panel shows it; both change it only through this class, so the
shuffle state can't get out of step with the items."""
import random

from .util import merge_in_name_order


def _path(item):
    return item["path"]


class PlayQueue:
    def __init__(self):
        self.items: list[dict] = []      # {"path", "title"?}
        self.index = -1                  # the one playing, -1 for none
        self.unshuffled = None           # the order before shuffling; None while shuffle is off

    # ---------------------------------------------------------------- reading
    @property
    def shuffled(self) -> bool:
        return self.unshuffled is not None

    def current(self):
        """The item playing, or None."""
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    def position_of(self, item) -> int:
        """Where this very item (not an equal one) sits now, or -1."""
        return next((i for i, x in enumerate(self.items) if x is item), -1)

    # ---------------------------------------------------------------- changing the order
    def reorder(self, new: list[dict], current=None):
        """Use `new` as the items; `current` (by identity) stays the one playing."""
        self.items = new
        self.index = self.position_of(current) if current is not None else -1

    def shuffle_on(self):
        """Mix up everything except what's playing, remembering the original order."""
        cur = self.current()
        self.unshuffled = list(self.items)
        rest = [x for x in self.items if x is not cur]
        random.shuffle(rest)
        self.reorder(([cur] if cur else []) + rest, cur)

    def shuffle_off(self):
        """Put the original order back. Anything added while shuffled goes after it."""
        if not self.shuffled:
            return
        cur = self.current()
        ids = {id(x) for x in self.items}
        new = [x for x in self.unshuffled if id(x) in ids]
        kept = {id(x) for x in new}
        new += [x for x in self.items if id(x) not in kept]
        self.unshuffled = None
        self.reorder(new, cur)

    def reset_shuffle(self):
        """A brand-new queue (a folder, a playlist, Clear) forgets the order from before."""
        self.unshuffled = None

    # ---------------------------------------------------------------- adding
    def merge_in_order(self, items):
        """Add items among the others in name order (#57); while shuffled, the order from before
        shuffling learns them too, so leaving Shuffle puts each one in its place."""
        cur = self.current()
        self.items = merge_in_name_order(self.items, items, _path)
        if cur is not None:
            self.index = self.position_of(cur)
        if self.shuffled:
            self.unshuffled = merge_in_name_order(self.unshuffled, items, _path)

    def shuffle_in(self, items, ordered=True):
        """In Shuffle mode, added items land at random places after what's playing (#65). The order
        from before shuffling learns them too (in name order, or at its end when not `ordered`)."""
        if not self.shuffled:            # e.g. the queue was empty or cleared: start remembering now
            self.unshuffled = list(self.items)
        self.unshuffled = (merge_in_name_order(self.unshuffled, items, _path) if ordered
                           else self.unshuffled + list(items))
        start = self.index + 1 if self.current() is not None else 0
        for it in items:
            self.items.insert(random.randint(start, len(self.items)), it)
