# Copyright (c) 2016 Philipp Lucas (philipp.lucas@uni-jena.de)
import math

# TODO: is it better to use immutable tuples instead of mutable lists for the internal representation of domains?


class NumericDomain:
    """A continuous domain that can be represented by an interval [min, max]."""

    def __init__(self, *args):
        """Constructs a numercial domain.
             * pass no arguments for an unbounded domain
             * pass one scalar argument for a singular domain
             * pass a list/tuple of two scalars for a bounded or partially unbounded domain:
                [lower, upper], [val, +math.inf] or [-math.inf, val]
             * or pass two scalars
        """
        l = len(args)
        if l == 0:
            self._value = [-math.inf, +math.inf]
        elif l == 1:
            arg = args[0]
            try:
                self._value = [arg[0], arg[1]]
            except (TypeError, KeyError, IndexError):  # 'number' is not subscriptable
                self._value = [arg, arg]
        elif l == 2:
            self._value = [args[0], args[1]]
        else:
            raise ValueError("Too many arguments given: " + str(args))
        self._validate()

    def __str__(self):
        return str(self._value)

    def _validate(self):
        if self._value[0] > self._value[1]:
            raise ValueError("resulting domain is empty: " + str(self._value))

    def issingular(self):
        return self._value[0] == self._value[1]

    def isbounded(self):
        return self._value[0] != -math.inf and self._value[1] != math.inf

#    this actually is: is neither unbounded nor singular
#    def isbounded(self):
#        return not self.issingular() and not self.isunbounded()

    def bounded(self, extent):
        if not self.isbounded():
            [l, h] = self._value
            try:
                [el, eh] = extent._value
            except AttributeError:
                [el, eh] = extent
            return NumericDomain(el if l == -math.inf else l, eh if h == math.inf else h)
        else:
            return self

    def value(self):
        return self._value[0] if self.issingular() else self._value

    def tojson(self):
        if self.isbounded():
            return self.value()
        else:
            [l, h] = self._value
            return [None if l == -math.inf else l, None if h == math.inf else h]

    def clamp(self, val):
        [l, h] = self._value
        if val < l:
            return l
        elif val > h:
            return h
        return val

    def intersect(self, domain):
        try:
            [l2, h2] = domain._value
        except AttributeError:
            [l2, h2] = NumericDomain(domain)._value
        [l1, h1] = self._value

        self._value = [
            l1 if l1 > l2 else l2,
            h1 if h1 < h2 else h2
        ]
        self._validate()
        return self

    def setlowerbound(self, value):
        if value > self._value[0]:
            self._value[0] = value
        self._validate()
        return self

    def setupperbound(self, value):
        if value < self._value[1]:
            self._value[1] = value
        self._validate()
        return self


class DiscreteDomain:
    """An (ordered) discrete domain that can be represented by a list of values [val1, val2, ... ]."""

    def __init__(self, *args):
        """Constructs a discrete domain.
             * pass no arguments for an unbounded domain
             * not anymore: pass one scalar argument for a singular domain
             * pass a list of values for a bounded domain. its order is preserved.
        """

        """Internal representation is as follows:
            * self._value == [math.inf] for an unbound domain
            * self._value == [single_value] for a singular domain that only contains single_value
            * self._value == [val1, ... , valn] for a bounded domain of val1, ..., valn
        """
        l = len(args)
        if l == 0:
            self._value = [math.inf]
        elif l == 1:
            # convert to array if its a single value
            val = args[0]
            self._value = [val] if isinstance(val, str) else val
        else:
            raise ValueError("Too many arguments given: " + str(args))
        self._validate()

    def __len__(self):
        return math.inf if not self.isbounded() else len(self._value)

    def __str__(self):
        return str(self._value)

    def _validate(self):
        if len(self._value) == 0:
            raise ValueError("domain must not be empty")

    def issingular(self):
        return len(self._value) == 1 and self.isbounded()

    def isbounded(self):
        return self._value[0] != math.inf

    def bounded(self, extent):
        if not self.isbounded():
            return extent if isinstance(extent, DiscreteDomain) else DiscreteDomain(extent)
        else:
            return self

    def value(self):
        return self._value[0] if self.issingular() else self._value

    def tojson(self):
        # requires special treatment, because math.inf would often not be handled correctly in JSON
        if self.isbounded():
            return self.value()
        else:
            return None

    def clamp(self, val):
        if not self.isbounded() or val in self._value:
            return val
        else:
            raise NotImplementedError("Don't know what to do.")

    def intersect(self, domain):
        try:
            dvalue = domain._value
        except AttributeError:
            dvalue = DiscreteDomain(domain)._value

        if not self.isbounded():
            self._value = dvalue
        else:
            self._value = [e for e in self._value if e in dvalue]
        self._validate()
        return self

    def setlowerbound(self, value):
        raise NotImplementedError
        # use slice with find to find index to slice from

    def setupperbound(self, value):
        raise NotImplementedError
