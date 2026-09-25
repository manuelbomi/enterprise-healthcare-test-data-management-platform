"""data_plane — PySpark jobs for discovery, subsetting, masking, and
synthetic data generation.

See ARCHITECTURE.md section 2.2 (repository root) for responsibilities and
boundaries. This package never makes authorization decisions and never
decides *whether* a job should run — that is the control plane's job
(ARCHITECTURE.md section 2.1); this package only knows *how* to do the
work once asked.
"""

__version__ = "0.1.0"
