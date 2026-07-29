suppressPackageStartupMessages(library(jsonlite))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("usage: summarize.R <input.json> <output.json> <artifact_dir>")
}

input_path <- args[[1]]
output_path <- args[[2]]
artifact_dir <- args[[3]]

payload <- fromJSON(input_path, simplifyVector = TRUE)
values <- as.numeric(payload$x)
if (length(values) == 0 || any(!is.finite(values))) {
  stop("input field 'x' must contain at least one finite numeric value")
}

result <- list(
  n = length(values),
  mean = mean(values),
  sd = if (length(values) > 1) sd(values) else 0
)

dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
dir.create(artifact_dir, recursive = TRUE, showWarnings = FALSE)
write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE)
writeLines(
  c(
    paste0("n=", result$n),
    paste0("mean=", format(result$mean, digits = 15)),
    paste0("sd=", format(result$sd, digits = 15))
  ),
  file.path(artifact_dir, "summary.txt"),
  useBytes = TRUE
)
