# Project: Webcam Schellbronn

Build a small, modular image-processing pipeline for a private home-network
camera that provides a live view of a village, rooftops, trees, sky and a
church tower with a visible clock.

The system has three logical components:

1. Camera source
2. Private image acquisition and storage
3. Image rendering and publishing

Do not assume a specific programming language, framework, cloud service,
image-processing library or deployment model unless required by the existing
project. Keep the implementation modular so these components can be replaced
independently.

## 1. Camera source

A Raspberry Pi 4 with a Sony IMX477 camera provides the original image.

The camera is only accessible inside the private home network.

The camera endpoint provides the latest original JPEG image.

The original image should be treated as the single source of truth.

The camera itself should not be responsible for the different public/private
image variants.

## 2. Image acquisition

A process running in the private network must periodically retrieve the
original JPEG from the Raspberry Pi.

Requirements:

- Retrieve the latest original image from the camera.
- Detect failed/unreachable camera requests.
- Do not overwrite a valid image with an invalid/empty response.
- Store the latest valid original image.
- Optionally keep a small number of previous originals for debugging or
  time-lapse functionality.
- Add a timestamp to the metadata/state associated with the image.
- The original image must remain private and must never be publicly exposed.

The acquisition process should be able to run unattended after system startup.

The exact mechanism for running this process is intentionally left open.

## 3. Original image

The original camera image is the master source for all transformations.

Never create one public variant from another public variant.

Every variant must always be generated directly from the original image.

This avoids cumulative quality loss and makes all image variants deterministic.

## 4. Image rendering

Create a separate image-rendering component.

It receives the original image and produces different derived images.

The renderer should be configurable without changing the core processing logic.

At minimum, support these variants:

### Variant A: Private live image

Purpose:
Personal use inside the private network.

Characteristics:

- Highest available quality.
- Full useful camera view.
- No privacy masking required because this version is private.
- May contain all visible rooftops and surrounding buildings.
- May optionally contain a timestamp.
- May optionally contain a watermark.
- Should preserve as much image detail as reasonably possible.

This is the version used by Home Assistant for personal viewing.

### Variant B: Public landscape image

Purpose:
Publicly accessible live webcam.

The composition should focus on:

- sky
- clouds
- horizon
- trees
- rooftops where appropriate
- church tower
- church clock

The composition should intentionally avoid unnecessarily exposing private
areas of neighboring properties.

The public image must include privacy protection.

Privacy protection must be configurable and should support at least:

- cropping
- rectangular masks
- polygon masks
- blur/pixelation of defined regions

The privacy regions must be configurable independently from the source image.

The goal is that windows of neighboring houses cannot be meaningfully inspected
in the public image.

The church tower and its clock should remain clearly visible.

The public image should look like an intentional landscape webcam rather than
a surveillance camera.

### Variant C: Wide-angle / artistic public view

Create another public-facing variant with a wider or more panoramic-looking
composition.

This variant may use a different crop, perspective treatment or lens-like
distortion to create a wider field of view.

Privacy protection must still be applied.

Neighboring windows and other unnecessarily private areas must remain protected.

The variant should remain visually useful and should emphasize:

- sky
- clouds
- horizon
- village
- trees
- church tower

Do not sacrifice privacy for the visual effect.

## 5. Cropping and zooming

The renderer must support configurable crop regions.

A crop configuration should be expressed independently of the source image's
absolute resolution where practical, so that the system can adapt if the
camera resolution changes.

Support:

- full image
- centered crop
- arbitrary crop
- zoom
- configurable output resolution
- configurable aspect ratio

The same original image should be capable of producing multiple different
compositions.

## 6. Watermarks

Support optional watermarks.

Watermarks must be configurable and must not be hard-coded into the image
processing logic.

Possible configuration:

- text
- position
- opacity
- size
- margin
- optional timestamp
- optional project name

The private image and public images should be able to have different
watermark settings.

The watermark must not reveal private information.

## 7. Timestamp

Support an optional timestamp overlay.

The timestamp should represent the time at which the source image was captured,
not merely the time at which a public request was made.

Use a clearly defined timezone.

The timestamp format should be configurable.

The church clock visible in the image is an important visual feature, but the
software should not attempt to modify or replace it.

## 8. Privacy is a first-class requirement

The public image must never expose the unrestricted original image.

Do not provide an HTTP/API endpoint that accidentally allows retrieval of the
original source image from the public side.

Privacy transformations must happen before an image becomes publicly
accessible.

Privacy configuration should be easy to adjust after visually inspecting the
camera output.

It should be possible to define permanent privacy zones for neighboring
windows or properties.

The system should make it difficult to accidentally publish the original.

## 9. Image processing pipeline

Conceptually the pipeline should be:

Original camera image
        |
        +--------------------+
        |                    |
        v                    v
Private renderer       Public renderer
        |                    |
        |              +-----+------+
        |              |            |
        |              v            v
        |        Landscape     Wide-angle
        |        public        public
        |              |            |
        |              +-----+------+
        |                    |
        v                    v
Private image          Privacy protection
                             |
                             v
                       Public image

Every output must be generated from the original source.

## 10. Caching

Rendering should not unnecessarily happen multiple times for the same source
image.

Use the source image identity/timestamp to determine whether a new rendering
is required.

If the source image has not changed, reuse the existing derived image.

When a new source image arrives, regenerate the configured variants.

Public requests should receive the latest valid rendered image quickly.

Do not make every public HTTP request trigger a complete image-processing
pipeline unless there is a specific reason.

## 11. Failure handling

The system must continue serving the last valid image if:

- the Raspberry Pi is temporarily unreachable
- the network fails
- image processing fails
- cloud storage is temporarily unavailable

Never replace a valid image with an error image.

Expose enough status information to determine:

- when the last camera image was received
- when each variant was last rendered
- whether the camera is reachable
- whether rendering is healthy
- whether the public image is current

## 12. Home Assistant integration

Home Assistant should be able to:

- retrieve/display the private live image
- retrieve the public image if needed
- determine when the last image was updated
- detect camera failures
- optionally trigger an immediate refresh
- optionally trigger regeneration of the derived images

The integration should remain simple and should not require Home Assistant to
know the details of the image-processing implementation.

## 13. Cloud/public publishing

The public variants may be stored or served through a cloud/public endpoint.

The architecture should allow the image renderer and public storage/delivery
to be located separately from the Home Assistant installation.

The public layer must only have access to already privacy-filtered images.

Do not expose the private source image to the public layer.

The public image should be cacheable.

Use cache invalidation/versioning based on the source-image timestamp or another
monotonic image version.

## 14. Configuration

All important image-specific settings should be configurable.

Do not hard-code values such as:

- crop coordinates
- output resolution
- privacy masks
- blur strength
- watermark
- timestamp format
- image quality
- variant names
- update interval

Configuration should be easy to change while tuning the camera.

It should be possible to experiment with different crops and privacy regions
without changing application logic.

## 15. Initial implementation priority

Implement the smallest useful end-to-end version first:

1. Retrieve original JPEG from Raspberry Pi.
2. Store the latest valid original privately.
3. Generate a private image.
4. Generate one privacy-safe public image.
5. Serve/store both variants.
6. Add configurable crop and privacy masks.
7. Add optional watermark and timestamp.
8. Add the second wide-angle/artistic variant.
9. Add health/status information.
10. Add caching and robust failure handling.

Do not over-engineer the first version.

The system should be easy to run unattended and easy to debug.

## 16. Important architectural principle

Separate these concerns:

- camera acquisition
- source image storage
- image transformation
- privacy protection
- public publishing
- Home Assistant integration

Do not tightly couple them.

The exact implementation technology is intentionally not specified.
Choose the simplest reliable implementation appropriate for the environment.

The final system should behave like a small dedicated "image appliance":
the Raspberry Pi produces the source image, the private system retrieves it,
and the renderer creates deterministic private and public representations
from that single source.