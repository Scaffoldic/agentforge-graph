<?php

use App\Http\Controllers\UserController;
use Illuminate\Support\Facades\Route;

Route::get('/users', [UserController::class, 'index']);
Route::post('/users', 'App\Http\Controllers\UserController@store');
Route::get('/health', function () {
    return 'ok';
});
