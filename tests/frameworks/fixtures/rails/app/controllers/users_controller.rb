class UsersController < ApplicationController
  def index
    render json: []
  end

  def create
    head :created
  end
end
