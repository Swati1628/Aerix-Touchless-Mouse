class AdaptiveSensitivity:
    def __init__(self):
        self.value = 1.0
    def increase(self):
        self.value = min(2.0, self.value + 0.1)
    def decrease(self):
        self.value = max(0.3, self.value - 0.1)
