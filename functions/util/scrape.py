GRAPHQL_QUERY = """
query GetHomeModules($country: Country!, $language: Language!, $platform: Platform!) {
  urlV2(fullPath: "/", site: "www") {
    node {
      ... on HomePage {
        modules {
          ... on HMTop10InYourCountry {
            titles {
              id
              objectType
              content(country: $country, language: $language) {
                title
                originalReleaseYear
                posterUrl
                genres {
                  translation(language: $language)
                }
                scoring {
                  imdbScore
                }
              }
              watchNowOffer(country: $country, platform: $platform) {
                standardWebURL
                package {
                  clearName
                  shortName
                  icon
                }
              }
            }
          }
        }
      }
    }
  }
}
"""
