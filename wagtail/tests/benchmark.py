from __future__ import absolute_import, unicode_literals

import time
import tracemalloc


class Benchmark():
    repeat = 10
    output_all_measurements = False
    output_summary = True

    def test(self):
        timings = []
        memory_usage = []
        tracemalloc.start()

        for i in range(self.repeat):
            before_memory = tracemalloc.take_snapshot()
            start_time = time.time()

            self.bench()

            end_time = time.time()
            after_memory = tracemalloc.take_snapshot()
            timings.append(end_time - start_time)
            memory_usage.append(sum([t.size for t in after_memory.compare_to(before_memory, 'filename')]))

        time_min = min(timings)
        time_max = max(timings)
        time_avg = sum(timings) / len(timings)

        memory_min = min(memory_usage)
        memory_max = max(memory_usage)
        memory_avg = int(sum(memory_usage) / len(memory_usage))

        if self.output_all_measurements:
            print('\n RUN ┆       TIME ┆     MEMORY ')
            for i in range(self.repeat):
                print('┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄')
                print(' {:3d} ┆ {:2.8f} ┆ {:10d}'.format(i + 1, timings[i], memory_usage[i]))

        print('\n     ┆       TIME ┆     MEMORY ')
        print('┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄')
        print(' MIN ┆ {:2.8f} ┆ {:10d} '.format(time_min, memory_min))
        print('┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄')
        print(' MAX ┆ {:2.8f} ┆ {:10d} '.format(time_max, memory_max))
        print('┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄┆┄┄┄┄┄┄┄┄┄┄┄┄')
        print(' AVG ┆ {:2.8f} ┆ {:10d} '.format(time_avg, memory_avg))
