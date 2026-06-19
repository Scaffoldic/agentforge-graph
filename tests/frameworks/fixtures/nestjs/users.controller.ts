import { Controller, Delete, Get, Post } from '@nestjs/common';

@Controller('users')
export class UsersController {
  @Get()
  findAll() {
    return [];
  }

  @Get(':id')
  findOne() {
    return {};
  }

  @Post()
  create() {
    return {};
  }

  @Delete(':id')
  remove() {
    return {};
  }
}

export class NotAController {
  helper() {
    return 1;
  }
}
