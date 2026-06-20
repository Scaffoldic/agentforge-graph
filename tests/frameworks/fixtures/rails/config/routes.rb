Rails.application.routes.draw do
  get "/users" => "users#index"
  post "/users", to: "users#create"
  root "home#show"
  resources :photos
end
