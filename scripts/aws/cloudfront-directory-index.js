function handler(event) {
  var request = event.request;
  var uri = request.uri;

  // If the URI ends with '/', append 'index.html'
  // so CloudFront fetches the actual file from S3
  // instead of getting a 403 AccessDenied for a
  // "directory" key that doesn't exist on S3.
  if (uri.endsWith('/')) {
    request.uri = uri + 'index.html';
  }

  return request;
}