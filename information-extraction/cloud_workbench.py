"""App Service web entry point; never starts an extraction worker."""

from information_extraction.workbench_cloud import render_cloud_workbench


render_cloud_workbench()
