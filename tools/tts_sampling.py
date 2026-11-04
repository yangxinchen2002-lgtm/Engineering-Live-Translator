"""Extended-duration variant of the existing 20 ms NVML sampler for CPU tests."""
import ctypes as ct
from tools.measure_local_translation import Sampler as ExistingSampler,Memory


class Sampler(ExistingSampler):
    def run(self):
        import time
        try:
            while not self.stop.is_set():
                memory=Memory();self.check(self.api.nvmlDeviceGetMemoryInfo(self.device,ct.byref(memory)))
                self.rows.append({'qpc_ns':time.perf_counter_ns(),'stage':self.stage,
                                  'used_bytes':memory.used,'total_bytes':memory.total})
                if len(self.rows)>100000:raise RuntimeError('sample capacity exceeded')
                self.stop.wait(.02)
        except Exception as error:self.error=str(error)
