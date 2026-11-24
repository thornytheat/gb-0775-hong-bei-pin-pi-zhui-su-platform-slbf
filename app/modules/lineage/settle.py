from fractions import Fraction


def solve_linear(matrix, values):
    """Solve A*x=b exactly with rational Gaussian elimination."""
    n = len(matrix)
    rows = [[Fraction(value) for value in matrix[index]] + [Fraction(values[index])]
            for index in range(n)]
    for column in range(n):
        pivot = next((row for row in range(column, n) if rows[row][column] != 0), None)
        if pivot is None:
            raise ZeroDivisionError('循环产地方程没有唯一解')
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [value / divisor for value in rows[column]]
        for row in range(n):
            if row == column:
                continue
            factor = rows[row][column]
            if factor:
                rows[row] = [current - factor * pivot_value
                             for current, pivot_value in zip(rows[row], rows[column])]
    return [rows[index][n] for index in range(n)]


def solve_loop_composition(members, inputs, jobs, coupons, genealogy):
    """
    Solve homogeneous origin mass around a return SCC.

    Equation for job i is C_i = K_i + sum(f_ij / M_j * C_j).  Moving the
    internal return terms to the left gives an exact rational linear system.
    A loop without external provenance is the homogeneous singular case.
    """
    ordered = sorted(members)
    index = {work: position for position, work in enumerate(ordered)}
    size = len(ordered)
    masses = [Fraction(jobs[work]['g']) for work in ordered]
    known = [{origin: Fraction(amount) for origin, amount in parts.items()}
             for parts in (_known_parts(work, inputs, coupons, genealogy, index)
                           for work in ordered)]
    origins = sorted({origin for parts in known for origin in parts})
    matrix = [[Fraction(1 if row == column else 0) for column in range(size)]
              for row in range(size)]
    for row, work in enumerate(ordered):
        for feed in inputs.get(work, []):
            if feed['source_kind'] != 'return':
                continue
            donor_work = coupons[feed['source']]['work']
            if donor_work not in index:
                continue
            column = index[donor_work]
            matrix[row][column] -= Fraction(feed['g']) / masses[column]
    compositions = {}
    for origin in origins:
        right = [parts.get(origin, Fraction()) for parts in known]
        answer = solve_linear(matrix, right)
        for position, value in enumerate(answer):
            if value:
                compositions.setdefault(ordered[position], {})[origin] = value
    external = {origin: sum((parts.get(origin, Fraction()) for parts in known), Fraction())
                for origin in origins}
    return ordered, compositions, external


def _known_parts(work, inputs, coupons, genealogy, loop_index):
    parts = {}
    for feed in inputs.get(work, []):
        amount = Fraction(feed['g'])
        if feed['source_kind'] == 'origin':
            key = feed['source']
            parts[key] = parts.get(key, Fraction()) + amount
            continue
        donor_work = coupons[feed['source']]['work']
        if donor_work in loop_index:
            continue
        parent = genealogy[donor_work]
        scale = amount / Fraction(parent['input_g'])
        for origin, value in parent['composition_g'].items():
            contribution = Fraction(value) * scale
            parts[origin] = parts.get(origin, Fraction()) + contribution
    return parts
