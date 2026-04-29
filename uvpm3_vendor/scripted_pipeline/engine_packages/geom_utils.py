from uvpm_core import IslandSet, CoordSpace, Box


def islands_inside_box(islands, box, fully_inside):

    islands_inside = IslandSet()

    if fully_inside:
        def inside_check(island):
            island_bbox = island.bbox()
            return island_bbox.within(box)
    else:
        def inside_check(island):
            return island.overlaps(box)
    
    for island in islands:
        if inside_check(island):
            islands_inside.append(island)

    return islands_inside


def array_bbox(array):
    bbox = Box.flipped_box()

    for elem in array:
        bbox.combine(elem.bbox())

    return bbox


class IslandWrapper:

    @staticmethod
    def is_valid_tdensity(tdensity_value):
        eps = 1.0e-5
        return tdensity_value > eps

    def __init__(self, island, scale_length=1.0):
        self._island = island
        self._scale_length = scale_length

    def get(self):
        return self._island
    
    def scale(self, factor, pivot=None):
        if not pivot:
            pivot = self._island.bbox().center()

        return IslandWrapper(self._island.scale(factor, factor, pivot), scale_length=self._scale_length)

    def calc_tdensity(self, tex_size):
        tdensity = self._island.texel_density(CoordSpace.GLOBAL)
        return tex_size * tdensity / self._scale_length

    def set_tdensity(self, tex_size, tdensity_value, pivot=None):


        assert tex_size > 0
        assert tdensity_value >= 0

        tdensity = self.calc_tdensity(tex_size)

        if not self.is_valid_tdensity(tdensity):
            raise ValueError()

        s_factor = tdensity_value / tdensity
        return self.scale(s_factor, pivot)
