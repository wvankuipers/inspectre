import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { InspectreApiService } from './inspectre-api.service';

describe('InspectreApiService', () => {
  let service: InspectreApiService;
  let httpController: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), InspectreApiService],
    });
    service = TestBed.inject(InspectreApiService);
    httpController = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpController.verify();
  });

  describe('suite()', () => {
    it('encodes projectSlug with special characters in the URL', () => {
      service.suite('my project', 'my suite').subscribe();
      const req = httpController.expectOne('/api/projects/my%20project/suites/my%20suite/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });

    it('encodes projectSlug with slash characters in the URL', () => {
      service.suite('proj/name', 'suite/name').subscribe();
      const req = httpController.expectOne('/api/projects/proj%2Fname/suites/suite%2Fname/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });

    it('leaves plain slugs unchanged', () => {
      service.suite('my-project', 'my-suite').subscribe();
      const req = httpController.expectOne('/api/projects/my-project/suites/my-suite/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('run()', () => {
    it('encodes projectSlug and suiteSlug with special characters in the URL', () => {
      service.run('my project', 'my suite', 42).subscribe();
      const req = httpController.expectOne('/api/projects/my%20project/suites/my%20suite/runs/42/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });

    it('encodes slugs with slash characters', () => {
      service.run('proj/name', 'suite/name', 1).subscribe();
      const req = httpController.expectOne('/api/projects/proj%2Fname/suites/suite%2Fname/runs/1/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });

    it('leaves plain slugs unchanged', () => {
      service.run('my-project', 'my-suite', 5).subscribe();
      const req = httpController.expectOne('/api/projects/my-project/suites/my-suite/runs/5/');
      expect(req.request.method).toBe('GET');
      req.flush({});
    });
  });

  describe('testsBulk()', () => {
    it('posts the given ids and returns the response body', () => {
      let result: unknown;
      service.testsBulk([1, 2, 3]).subscribe((r) => (result = r));
      const req = httpController.expectOne('/api/tests/bulk/');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ ids: [1, 2, 3] });
      req.flush([{ id: 1 }, { id: 2 }, { id: 3 }]);
      expect(result).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }]);
    });

    it('posts an empty array when given no ids', () => {
      service.testsBulk([]).subscribe();
      const req = httpController.expectOne('/api/tests/bulk/');
      expect(req.request.body).toEqual({ ids: [] });
      req.flush([]);
    });
  });
});
