"""Environment object for compiler.

This module contains the various column accessors and function evaluators that
are made available by the query compiler via their compilation context objects.
Define new columns and functions here.
"""
import copy
import datetime
import re

from beancount.core.amount import Decimal
from beancount.core.amount import ZERO
from beancount.core.data import Transaction
from beancount.core.compare import hash_entry
from beancount.core import interpolate
from beancount.core import amount
from beancount.core import position
from beancount.core import inventory
from beancount.core import account
from beancount.core import data
from beancount.query import query_compile as c


# Non-agreggating functions. These functionals maintain no state.

class Length(c.EvalFunction):
    "Compute the length of the argument. This works on sequences."
    __intypes__ = [(list, set, str)]

    def __init__(self, operands):
        super().__init__(operands, int)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return len(args[0])

class Str(c.EvalFunction):
    "Convert the argument to a string."
    __intypes__ = [object]

    def __init__(self, operands):
        super().__init__(operands, str)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return repr(args[0])


# Operations on dates.

class Year(c.EvalFunction):
    "Extract the year from a date."
    __intypes__ = [datetime.date]

    def __init__(self, operands):
        super().__init__(operands, int)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return args[0].year

class Month(c.EvalFunction):
    "Extract the month from a date."
    __intypes__ = [datetime.date]

    def __init__(self, operands):
        super().__init__(operands, int)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return args[0].month

class Day(c.EvalFunction):
    "Extract the day from a date."
    __intypes__ = [datetime.date]

    def __init__(self, operands):
        super().__init__(operands, int)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return args[0].day

class Weekday(c.EvalFunction):
    "Extract a 3-letter weekday from a date."
    __intypes__ = [datetime.date]

    def __init__(self, operands):
        super().__init__(operands, str)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return args[0].strftime('%a')


# Operations on accounts.

class Parent(c.EvalFunction):
    "Get the parent name of the account."
    __intypes__ = [str]

    def __init__(self, operands):
        super().__init__(operands, str)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return account.parent(args[0])


# Operation on inventories.

class UnitsPosition(c.EvalFunction):
    "Get the number of units of a position (stripping cost)."
    __intypes__ = [position.Position]

    def __init__(self, operands):
        super().__init__(operands, amount.Amount)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return args[0].get_units()

class CostPosition(c.EvalFunction):
    "Get the cost of a position."
    __intypes__ = [position.Position]

    def __init__(self, operands):
        super().__init__(operands, amount.Amount)

    def __call__(self, posting):
        args = self.eval_args(posting)
        return args[0].get_cost()

SIMPLE_FUNCTIONS = {
    'str'                          : Str,
    'length'                       : Length,
    'parent'                       : Parent,
    ('units', position.Position)   : UnitsPosition,
    ('cost', position.Position)    : CostPosition,
    'year'                         : Year,
    'month'                        : Month,
    'day'                          : Day,
    'weekday'                      : Weekday,
    }




# Aggregating functions. These instances themselves both make the computation
# and manage state for a single iteration.

class Count(c.EvalAggregator):
    "Count the number of occurrences of the argument."
    __intypes__ = [object]

    def __init__(self, operands):
        super().__init__(operands, int)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = 0

    def update(self, store, unused_ontext):
        store[self.handle] += 1

    def finalize(self, store):
        return store[self.handle]

class Sum(c.EvalAggregator):
    "Calculate the sum of the numerical argument."
    __intypes__ = [(int, float, Decimal)]

    def __init__(self, operands):
        super().__init__(operands, operands[0].dtype)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = self.dtype()

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        store[self.handle] += value

    def finalize(self, store):
        return store[self.handle]

class SumBase(c.EvalAggregator):

    def __init__(self, operands):
        super().__init__(operands, inventory.Inventory)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = inventory.Inventory()

    def finalize(self, store):
        return store[self.handle]

class SumAmount(SumBase):
    "Calculate the sum of the amount. The result is an Inventory."
    __intypes__ = [amount.Amount]

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        store[self.handle].add_amount(value)

class SumPosition(SumBase):
    "Calculate the sum of the position. The result is an Inventory."
    __intypes__ = [position.Position]

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        store[self.handle].add_position(value)

class SumInventory(SumBase):
    "Calculate the sum of the inventories. The result is an Inventory."
    __intypes__ = [inventory.Inventory]

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        store[self.handle].add_inventory(value)

class First(c.EvalAggregator):
    "Keep the first of the values seen."
    __intypes__ = [object]

    def __init__(self, operands):
        super().__init__(operands, operands[0].dtype)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = None

    def update(self, store, posting):
        if store[self.handle] is None:
            value = self.eval_args(posting)[0]
            store[self.handle] = value

    def finalize(self, store):
        return store[self.handle]

class Last(c.EvalAggregator):
    "Keep the last of the values seen."
    __intypes__ = [object]

    def __init__(self, operands):
        super().__init__(operands, operands[0].dtype)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = None

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        store[self.handle] = value

    def finalize(self, store):
        return store[self.handle]

class Min(c.EvalAggregator):
    "Compute the minimum of the values."
    __intypes__ = [object]

    def __init__(self, operands):
        super().__init__(operands, operands[0].dtype)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = self.dtype()

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        if value < store[self.handle]:
            store[self.handle] = value

    def finalize(self, store):
        return store[self.handle]

class Max(c.EvalAggregator):
    "Compute the maximum of the values."
    __intypes__ = [object]

    def __init__(self, operands):
        super().__init__(operands, operands[0].dtype)

    def allocate(self, allocator):
        self.handle = allocator.allocate()

    def initialize(self, store):
        store[self.handle] = self.dtype()

    def update(self, store, posting):
        value = self.eval_args(posting)[0]
        if value > store[self.handle]:
            store[self.handle] = value

    def finalize(self, store):
        return store[self.handle]

AGGREGATOR_FUNCTIONS = {
    ('sum', amount.Amount)       : SumAmount,
    ('sum', position.Position)   : SumPosition,
    ('sum', inventory.Inventory) : SumInventory,
    'sum'                        : Sum,
    'count'                      : Count,
    'first'                      : First,
    'last'                       : Last,
    'min'                        : Min,
    'max'                        : Max,
    }




# Column accessors for entries.

class IdEntryColumn(c.EvalColumn):
    "Unique id of a directive."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(str)

    def __call__(self, entry):
        return hash_entry(entry)

class TypeEntryColumn(c.EvalColumn):
    "The data type of the directive."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(str)

    def __call__(self, entry):
        return type(entry).__name__.lower()

class FilenameEntryColumn(c.EvalColumn):
    "The filename where the directive was parsed from or created."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(str)

    def __call__(self, entry):
        return entry.source.filename

class LineNoEntryColumn(c.EvalColumn):
    "The line number from the file the directive was parsed from."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(int)

    def __call__(self, entry):
        return entry.source.lineno

class DateEntryColumn(c.EvalColumn):
    "The date of the directive."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(datetime.date)

    def __call__(self, entry):
        return entry.date

class YearEntryColumn(c.EvalColumn):
    "The year of the date of the directive."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(int)

    def __call__(self, entry):
        return entry.date.year

class MonthEntryColumn(c.EvalColumn):
    "The month of the date of the directive."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(int)

    def __call__(self, entry):
        return entry.date.month

class DayEntryColumn(c.EvalColumn):
    "The day of the date of the directive."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(int)

    def __call__(self, entry):
        return entry.date.day

class FlagEntryColumn(c.EvalColumn):
    "The flag the transaction."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(str)

    def __call__(self, entry):
        return (entry.flag
                if isinstance(entry, Transaction)
                else None)

class PayeeEntryColumn(c.EvalColumn):
    "The payee of the transaction."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(str)

    def __call__(self, entry):
        return (entry.payee or ''
                if isinstance(entry, Transaction)
                else None)

class NarrationEntryColumn(c.EvalColumn):
    "The narration of the transaction."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(str)

    def __call__(self, entry):
        return (entry.narration or ''
                if isinstance(entry, Transaction)
                else None)

# A globally available empty set to fill in for None's.
EMPTY_SET = frozenset()

class TagsEntryColumn(c.EvalColumn):
    "The set of tags of the transaction."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(set)

    def __call__(self, entry):
        return (entry.tags or EMPTY_SET
                if isinstance(entry, Transaction)
                else EMPTY_SET)

class LinksEntryColumn(c.EvalColumn):
    "The set of links of the transaction."
    __intypes__ = [data.Transaction]

    def __init__(self):
        super().__init__(set)

    def __call__(self, entry):
        return (entry.links or EMPTY_SET
                if isinstance(entry, Transaction)
                else EMPTY_SET)




class MatchAccount(c.EvalFunction):
    """A predicate, true if the transaction has at least one posting matching
    the regular expression argument."""
    __intypes__ = [str]

    def __init__(self, operands):
        super().__init__(operands, bool)

    def __call__(self, entry):
        if not isinstance(entry, Transaction):
            return False
        pattern = self.eval_args(entry)[0]
        search = re.compile(pattern, re.IGNORECASE).search
        return any(search(posting.account) for posting in entry.postings)

# Functions defined only on entries.
ENTRY_FUNCTIONS = {
    'has_account' : MatchAccount,
    }


class FilterEntriesEnvironment(c.CompilationEnvironment):
    """An execution context that provides access to attributes on Transactions
    and other entry types.
    """
    context_name = 'FROM clause'
    columns = {
        'id'        : IdEntryColumn,
        'type'      : TypeEntryColumn,
        'filename'  : FilenameEntryColumn,
        'lineno'    : LineNoEntryColumn,
        'date'      : DateEntryColumn,
        'year'      : YearEntryColumn,
        'month'     : MonthEntryColumn,
        'day'       : DayEntryColumn,
        'flag'      : FlagEntryColumn,
        'payee'     : PayeeEntryColumn,
        'narration' : NarrationEntryColumn,
        'tags'      : TagsEntryColumn,
        'links'     : LinksEntryColumn,
        }
    functions = copy.copy(SIMPLE_FUNCTIONS)
    functions.update(ENTRY_FUNCTIONS)




# Column accessors for postings.

class IdColumn(c.EvalColumn):
    "The unique id of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return hash_entry(posting.entry)

class TypeColumn(c.EvalColumn):
    "The data type of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return type(posting.entry).__name__.lower()

class FilenameColumn(c.EvalColumn):
    "The filename where the posting was parsed from or created."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.entry.source.filename

class LineNoColumn(c.EvalColumn):
    "The line number from the file the posting was parsed from."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(int)

    def __call__(self, posting):
        return posting.entry.source.lineno

class DateColumn(c.EvalColumn):
    "The date of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(datetime.date)

    def __call__(self, posting):
        return posting.entry.date

class YearColumn(c.EvalColumn):
    "The year of the date of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(int)

    def __call__(self, posting):
        return posting.entry.date.year

class MonthColumn(c.EvalColumn):
    "The month of the date of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(int)

    def __call__(self, posting):
        return posting.entry.date.month

class DayColumn(c.EvalColumn):
    "The day of the date of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(int)

    def __call__(self, posting):
        return posting.entry.date.day

class FlagColumn(c.EvalColumn):
    "The flag of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.entry.flag

class PayeeColumn(c.EvalColumn):
    "The payee of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.entry.payee or ''

class NarrationColumn(c.EvalColumn):
    "The narration of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.entry.narration

class TagsColumn(c.EvalColumn):
    "The set of tags of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(set)

    def __call__(self, posting):
        return posting.entry.tags or EMPTY_SET

class LinksColumn(c.EvalColumn):
    "The set of links of the parent transaction for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(set)

    def __call__(self, posting):
        return posting.entry.links or EMPTY_SET

class PostingFlagColumn(c.EvalColumn):
    "The flag of the posting itself."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.flag

class AccountColumn(c.EvalColumn):
    "The account of the posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.account

class NumberColumn(c.EvalColumn):
    "The number of units of the posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(Decimal)

    def __call__(self, posting):
        return posting.position.number

class CurrencyColumn(c.EvalColumn):
    "The currency of the posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.position.lot.currency

class CostNumberColumn(c.EvalColumn):
    "The number of cost units of the posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(Decimal)

    def __call__(self, posting):
        return posting.position.lot.cost.number if posting.position.lot.cost else ZERO

class CostCurrencyColumn(c.EvalColumn):
    "The cost currency of the posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(str)

    def __call__(self, posting):
        return posting.position.lot.cost.currency if posting.position.lot.cost else ''

class ChangeColumn(c.EvalColumn):
    "The position for the posting. These can be summed into inventories."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(position.Position)

    def __call__(self, posting):
        return posting.position

class PriceColumn(c.EvalColumn):
    "The price attached to the posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(amount.Amount)

    def __call__(self, posting):
        return posting.price

class WeightColumn(c.EvalColumn):
    "The computed weight used for this posting."
    __intypes__ = [data.Posting]

    def __init__(self):
        super().__init__(amount.Amount)

    def __call__(self, posting):
        return interpolate.get_balance_amount(posting)

class FilterPostingsEnvironment(c.CompilationEnvironment):
    """An execution context that provides access to attributes on Postings.
    """
    context_name = 'WHERE clause'
    columns = {
        'id'            : IdColumn,
        'type'          : TypeColumn,
        'filename'      : FilenameColumn,
        'lineno'        : LineNoColumn,
        'date'          : DateColumn,
        'year'          : YearColumn,
        'month'         : MonthColumn,
        'day'           : DayColumn,
        'flag'          : FlagColumn,
        'payee'         : PayeeColumn,
        'narration'     : NarrationColumn,
        'tags'          : TagsColumn,
        'links'         : LinksColumn,
        'posting_flag'  : PostingFlagColumn,
        'account'       : AccountColumn,
        'number'        : NumberColumn,
        'currency'      : CurrencyColumn,
        'cost_number'   : CostNumberColumn,
        'cost_currency' : CostCurrencyColumn,
        'change'        : ChangeColumn,
        'price'         : PriceColumn,
        'weight'        : WeightColumn,
        }
    functions = copy.copy(SIMPLE_FUNCTIONS)

class TargetsEnvironment(FilterPostingsEnvironment):
    """An execution context that provides access to attributes on Postings.
    """
    context_name = 'targets/column'
    functions = copy.copy(FilterPostingsEnvironment.functions)
    functions.update(AGGREGATOR_FUNCTIONS)

    # The list of columns that a wildcard will expand into.
    wildcard_columns = 'date flag payee narration change'.split()
