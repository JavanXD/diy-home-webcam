# Project: DIY home webcam — Raspberry Pi Camera Appliance

Build the complete Raspberry Pi side of the project.

The Raspberry Pi is a dedicated headless camera appliance.

Hardware:

- Raspberry Pi 4
- Raspberry Pi High Quality Camera
- Sony IMX477
- C/CS mount lens
- Raspberry Pi OS Lite
- Ethernet or Wi-Fi
- No graphical desktop
- No monitor or keyboard required during normal operation

The Raspberry Pi must only be responsible for capturing and serving the
original camera image and exposing operational status.

All image transformations, privacy filtering, public rendering, watermarking
and publishing belong to the downstream image-processing system.

Do not implement image privacy processing on the Raspberry Pi.

==================================================
1. HEADLESS OPERATING SYSTEM
==================================================

Target Raspberry Pi OS Lite.

The system must operate completely headless.

The application must not require:

- graphical desktop
- X11
- Wayland
- browser
- monitor
- keyboard
- mouse

The Raspberry Pi should be configurable using Raspberry Pi Imager before
first boot.

SSH must be supported for administration.

Prefer SSH public-key authentication.

Do not require password authentication for normal administration.

The application must run correctly after reboot without any interactive
login.

==================================================
2. REPOSITORY STRUCTURE
==================================================

Create a clean repository structure separating:

- application code
- configuration
- systemd units
- installation/provisioning
- deployment
- operational scripts
- documentation
- tests

The exact directory names are up to the implementation, but the separation
must be clear.

The repository must contain enough information to recreate the complete
application on a fresh Raspberry Pi OS Lite installation.

Do not rely on undocumented manual steps.

==================================================
3. CAMERA CAPTURE
==================================================

Use the current Raspberry Pi camera stack available on the target Raspberry
Pi OS release.

Do not use the deprecated legacy Raspberry Pi camera stack.

The application must detect the connected camera.

At startup, verify that a supported camera is available.

The application must expose camera information through the health/status
interface.

The application must be able to capture a high-quality JPEG from the IMX477.

The capture configuration must be configurable.

At minimum support configuration for:

- width
- height
- JPEG quality
- exposure settings where appropriate
- white balance settings where appropriate
- capture timeout
- capture interval

Do not unnecessarily hard-code camera parameters.

The initial default should favor image quality over CPU usage.

The application should capture the highest useful resolution supported by the
camera without making the system unnecessarily slow.

==================================================
4. IMAGE LIFECYCLE
==================================================

Maintain one latest valid source image.

The source image must be treated as immutable after successful capture.

Do not modify the source image for:

- cropping
- resizing
- privacy filtering
- watermarking
- timestamp overlays
- public publishing

Those operations belong to downstream systems.

The application must write images atomically.

Never allow an HTTP request to receive a partially written JPEG.

Use a temporary file followed by an atomic replacement.

If a new capture fails:

- retain the previous valid image
- record the error
- increment a failure counter
- expose the failure through the health endpoint
- continue operating

A transient camera failure must not crash the entire service.

==================================================
5. HTTP API
==================================================

Expose a small internal HTTP API.

The exact HTTP framework is up to the implementation.

The API must listen only on the configured local/private network interface
and must not be exposed to the public Internet by default.

Required endpoints:

GET /raw.jpg

Returns the latest valid JPEG.

If no successful image has ever been captured, return an appropriate error
instead of returning a fake or empty image.

GET /health

Returns machine-readable health information.

Include at least:

- application status
- camera detected
- camera model
- last successful capture timestamp
- age of current image
- last capture duration
- last capture error
- consecutive failure count
- total successful captures
- total failed captures
- application version
- system uptime

GET /status

Returns more detailed operational information useful for troubleshooting.

This endpoint may include:

- camera configuration
- current resolution
- JPEG quality
- configured capture interval
- image size
- image timestamp
- process information
- system information
- service version

Do not expose secrets through any endpoint.

==================================================
6. OPTIONAL CONTROL ENDPOINT
==================================================

Provide an internal endpoint for manually triggering a capture.

For example:

POST /capture

This must be protected against accidental or abusive repeated requests.

The endpoint is intended for troubleshooting and Home Assistant integration.

It must not allow arbitrary command execution.

Never expose a generic shell/command endpoint over HTTP.

==================================================
7. HEALTH SEMANTICS
==================================================

Define clear health states.

Example:

HEALTHY

- camera available
- recent successful image
- capture service running

DEGRADED

- service running
- camera temporarily unavailable
- previous valid image still available

UNHEALTHY

- service cannot capture images
- no valid image exists
- internal fatal configuration problem

The health endpoint should provide enough information for Home Assistant to
detect a broken camera without relying on log parsing.

==================================================
8. SYSTEMD
==================================================

Create a dedicated systemd service for the camera application.

The service must:

- start automatically after boot
- wait until the network is available
- restart automatically after unexpected failure
- use a dedicated non-root user
- have a restricted working directory
- use explicit environment/configuration
- write logs to journald
- stop cleanly
- handle SIGTERM correctly

Do not run the application as root unless there is a documented hardware
requirement.

The service should use sensible systemd hardening where compatible with the
camera stack.

Examples of hardening to consider:

- NoNewPrivileges
- PrivateTmp
- ProtectSystem
- ProtectHome
- RestrictAddressFamilies
- ReadWritePaths

Do not blindly enable security options that prevent the camera stack from
working. Test them.

Provide commands/documentation for:

- install service
- enable service
- start service
- stop service
- restart service
- view status
- view logs
- uninstall service

==================================================
9. BOOT BEHAVIOR
==================================================

After power is connected:

1. Raspberry Pi boots.
2. Network becomes available.
3. Camera application starts automatically.
4. Camera is detected.
5. Application begins capturing images.
6. HTTP API becomes available.
7. Home Assistant can retrieve /raw.jpg.
8. /health reports operational state.

No manual login must be required.

==================================================
10. FIRST-BOOT / PROVISIONING
==================================================

Create an automated provisioning process for a fresh Raspberry Pi OS Lite
installation.

The provisioning process should install and configure everything required
for the camera application.

It should:

- verify supported OS/platform
- install required system dependencies
- install the application
- create the dedicated service user if required
- install configuration
- install systemd units
- configure directories and permissions
- enable the systemd service
- start the service
- perform a health check
- perform a camera detection check
- perform a test capture
- verify that /raw.jpg works
- verify that /health works

The provisioning process must be idempotent.

Running it twice must not corrupt the installation.

Do not overwrite user configuration without explicit instruction.

==================================================
11. CONFIGURATION
==================================================

Keep configuration separate from application code.

Configuration must support:

- HTTP bind address
- HTTP port
- capture resolution
- JPEG quality
- capture interval
- camera settings
- image storage location
- logging level
- health thresholds

Use sensible defaults.

Do not store passwords, private keys or other secrets in Git.

Provide an example configuration file.

Clearly document which values are safe to change.

==================================================
12. LOGGING
==================================================

Provide structured and useful operational logging.

Log:

- application startup
- application version
- camera detection
- camera configuration
- successful captures
- capture duration
- image size
- capture failures
- HTTP server startup
- unexpected exceptions
- graceful shutdown

Avoid logging the image itself.

Avoid excessive logging for successful periodic captures.

The service must not fill the SD card with logs.

==================================================
13. METRICS / DIAGNOSTICS
==================================================

Provide enough diagnostics to troubleshoot the system remotely.

At minimum track:

- successful captures
- failed captures
- consecutive failures
- last successful capture
- last failed capture
- last capture duration
- current image size
- service uptime

Expose these through /health or /status.

Keep the implementation lightweight.

==================================================
14. STORAGE
==================================================

The Pi should not continuously accumulate images.

Default behavior:

- retain only the latest source image
- optionally retain a small configurable number of diagnostic images

Do not implement long-term time-lapse storage on the Pi unless explicitly
enabled.

The SD card should not slowly fill up during normal operation.

==================================================
15. SECURITY
==================================================

Treat the Raspberry Pi as an internal network service.

Requirements:

- no public Internet listener
- no authentication bypass
- no arbitrary command execution
- no shell execution through HTTP parameters
- no secrets in source control
- least-privilege service account
- atomic image writes
- safe input handling
- bounded request sizes
- sensible HTTP timeouts
- graceful handling of malformed requests

The camera endpoint should only provide the source image.

Do not provide an endpoint that exposes arbitrary filesystem paths.

Do not provide an endpoint that executes arbitrary rpicam commands.

==================================================
16. DEPLOYMENT FROM DEVELOPMENT MACHINE
==================================================

The repository must support deploying the application to the Raspberry Pi
over SSH.

The development workflow should be:

Developer/Cursor
      |
      | SSH
      v
Raspberry Pi
      |
      v
Install/update application
      |
      v
Restart service
      |
      v
Health check

The deployment process should:

1. Verify SSH connectivity.
2. Verify the target host.
3. Upload only the required application files.
4. Preserve persistent configuration.
5. Install/update dependencies only when required.
6. Validate the deployment.
7. Restart the service when necessary.
8. Wait for the service to become healthy.
9. Retrieve /health.
10. Retrieve /raw.jpg.
11. Fail clearly if the deployment is unhealthy.

The deployment must be safe to run repeatedly.

==================================================
17. ROLLBACK
==================================================

Deployment must support rollback.

Before replacing a working application version:

- identify the currently deployed version
- retain the previous known-good version
- deploy the new version
- run health checks
- automatically roll back if startup or health checks fail

Never leave the Raspberry Pi in a known broken state because a deployment
failed halfway through.

==================================================
18. VERSIONING
==================================================

The application must expose its version.

The deployed version should be visible through /health.

The deployment process should report:

- local version
- remote version
- deployment result

Avoid relying only on timestamps to identify deployments.

==================================================
19. DEVELOPMENT WORKFLOW
==================================================

The project must be designed for development through Cursor.

Cursor should be able to:

- inspect the repository
- inspect the Raspberry Pi through SSH
- modify application code
- run local tests
- deploy to the Raspberry Pi
- inspect service status
- inspect logs
- retrieve /health
- retrieve /raw.jpg
- troubleshoot failures
- redeploy changes

Document the SSH configuration required for Cursor.

Prefer SSH keys over passwords.

Do not put private SSH keys into the repository.

==================================================
20. REMOTE DEVELOPMENT SAFETY
==================================================

The deployment workflow must distinguish between:

DEVELOPMENT

Changes can be made and tested freely.

DEPLOYMENT

Changes are copied to the Raspberry Pi.

PRODUCTION-LIKE STATE

The currently running version must remain recoverable.

A deployment must never blindly overwrite the only working copy.

Do not implement unrestricted automatic self-modification of the Raspberry Pi
from arbitrary remote input.

If automatic updates are implemented, they must use a controlled and
verifiable release mechanism.

==================================================
21. AUTOMATIC UPDATE OPTION
==================================================

Implement the architecture so automatic updates can be added later.

Do not make unattended Git pulls the default update mechanism.

If automatic updates are enabled later, require:

- trusted update source
- explicit version
- integrity verification
- health check after update
- rollback on failure
- protection against partial updates
- protection against downgrade attacks where appropriate

The default deployment model should remain:

Cursor/developer -> SSH -> deploy -> validate.

==================================================
22. TESTING
==================================================

Provide tests for:

- camera detection failure
- successful capture
- capture failure
- corrupted/empty camera output
- atomic image replacement
- HTTP /raw.jpg
- HTTP /health
- HTTP /status
- manual capture
- service restart
- configuration validation
- deployment validation

Where physical camera hardware is unavailable, provide a test mode using a
fixture JPEG.

The application must therefore be testable without an actual camera.

==================================================
23. SIMULATION MODE
==================================================

Implement a development/test mode that uses a static test image instead of
the physical camera.

This allows:

- local development
- CI testing
- HTTP API testing
- image processing integration testing
- deployment testing without repeatedly using the physical camera

The simulation mode must be clearly separated from production mode.

==================================================
24. DOCUMENTATION
==================================================

Create documentation covering:

- hardware requirements
- Raspberry Pi OS installation
- Raspberry Pi Imager configuration
- SSH setup
- first provisioning
- camera testing
- service management
- API endpoints
- configuration
- troubleshooting
- deployment
- rollback
- recovery
- simulation mode

Include a concise quick-start section.

The documentation must allow a fresh Raspberry Pi to be rebuilt without
depending on undocumented knowledge.

==================================================
25. ACCEPTANCE CRITERIA
==================================================

The implementation is complete when:

1. A fresh Raspberry Pi OS Lite installation can be provisioned automatically.
2. The IMX477 is detected.
3. A high-quality JPEG can be captured.
4. The service starts automatically after reboot.
5. /raw.jpg returns the latest valid JPEG.
6. /health reports useful operational information.
7. /status provides troubleshooting information.
8. Home Assistant can retrieve the image over the LAN.
9. Camera failures do not destroy the last valid image.
10. The service automatically recovers from crashes.
11. Cursor can deploy updates through SSH.
12. Deployments are validated automatically.
13. A failed deployment can be rolled back.
14. No GUI is required.
15. No long-term image accumulation occurs by default.
16. The original source image never becomes publicly accessible.
17. The implementation can later integrate with the downstream image renderer
    and Cloudflare publishing system.

Do not over-engineer the implementation.

Prefer a small, understandable and robust camera appliance over a large
framework-heavy application.