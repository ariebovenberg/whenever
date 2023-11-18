class AlwaysEqual:
    def __eq__(self, other):
        return True


class NeverEqual:
    def __eq__(self, other):
        return False


class AlwaysLarger:
    def __lt__(self, other):
        return False

    def __le__(self, other):
        return False

    def __gt__(self, other):
        return True

    def __ge__(self, other):
        return True


class AlwaysSmaller:
    def __lt__(self, other):
        return True

    def __le__(self, other):
        return True

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return False
