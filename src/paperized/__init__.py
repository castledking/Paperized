"""Paperized — convert a Minecraft mod's blocks into CraftEngine content.

The conversion is the easy part. The constraint is that CraftEngine binds a custom block
to a *vanilla* block state for its model and collision, and that state is a single-bind
finite resource. Borrow one that vanilla can still reach and real blocks render as your
model; overwrite one whose blockstate is multipart and every vanilla state you did not
allocate loses its model entirely.

So the job here is not "generate blocks", it is "generate only the blocks that are
provably safe, and explain every one that is not". See docs/carrier-safety.md.
"""

__version__ = "0.1.0"
